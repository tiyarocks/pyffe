import os
import caffe
import logging
from caffe import layers as L, NetSpec
from caffe.proto.caffe_pb2 import NetParameter
import argparse

class Model (object):

	def __init__(self, input_format, **kwargs):
		self.__dict__['infmt'] = input_format
		self.__dict__['params'] = dict(
			name='unnamed_net',
			batch_size=64,
			batch_sizes=[64, 64], # respectively train and val batch sizes
			channels=3,
			pretrain=None,
			optimal_batch_size=None
		)
		
		if 'batch_sizes' in kwargs and type(kwargs['batch_sizes']) is not list:
			kwargs['batch_sizes'] = [kwargs['batch_sizes'], kwargs['batch_sizes']]
		
		self.params.update(kwargs)
		
	def __getattr__(self, name):
		if name in self.__dict__:
			return self.__dict__[name]
		if name in self.params:
			return self.params[name]
		
		raise AttributeError("No attribute called {} is present".format(name))
	
	def __setattr__(self, name, value):
		if name in self.params:
			self.params[name] = value
		else:
			object.__setattr__(self, name, value)
			
	def get_train_batch_size(self):
		return self.batch_sizes[0]
		
	def get_val_batch_size(self):
		return self.batch_sizes[1]
		
	def optimize_batch_size(self):
		if self.optimal_batch_size is not None:
			self.batch_size = self.optimal_batch_size
			return self.optimal_batch_size
			
		feas = 1
		l,u = 1, 2048
		logging.info("Optimizing batch size... ")
		
		while l <= u:
			c = (l+u)/2
			self.batch_size = c
			with open("tmp.prototxt", "w") as f:
				f.write(self.to_deploy_prototxt(optimize=False))
			
			ret = os.system("caffe-try-batch-size tmp.prototxt")

			if ret == 0: # feasible
				logging.debug("Feasible batch size of {}".format(c))
				feas = c
				l = c + 1
			else:
				u = c - 1
		
		os.remove("tmp.prototxt")
		self.batch_size = feas
		self.optimal_batch_size = feas
		logging.info("Max batch in gpu mem: {}".format(feas))
		return feas
		
	def deploy_head(self):
		net = NetParameter()
		net.name = self.name
		net.input.append("data")
		inshape = net.input_shape.add()
		inshape.dim.append(self.batch_size)
		inshape.dim.append(self.channels)
		inshape.dim.append(self.infmt.crop_size)
		inshape.dim.append(self.infmt.crop_size)
		return net		
		
	def deploy_tail(self, last_top):
		n = NetSpec()
		n.score = L.Softmax(bottom=last_top)
		return n.to_proto()		
		
	def train_head(self, subset):
		n = NetSpec()
		# train
		image_data_param = dict(
			source = subset.list_absolute_path,
			batch_size = self.batch_sizes[0],
			new_width = self.infmt.new_width,
			new_height = self.infmt.new_height,
			root_folder = subset.root_folder,
			rand_skip = self.batch_size,
			shuffle = True
		)
		
		transform_param = dict(
			mirror = self.infmt.mirror,
			crop_size = self.infmt.crop_size,
			# mean_value = self.infmt.mean_pixel,
		)
		
		if self.infmt.scale is not None:
			transform_param['scale'] = self.infmt.scale
		
		if self.infmt.mean_file is not None:
			transform_param['mean_file'] = self.infmt.mean_file
		else:
			transform_param['mean_value'] = self.infmt.mean_pixel
		
		n.data, n.label = L.ImageData(ntop=2, image_data_param=image_data_param, transform_param=transform_param) #, include=dict(phase=caffe.TRAIN))
		net = n.to_proto()
		
		net.name = self.name
		return net
		
	def val_head(self, subset):
		image_data_param = dict(
			source = subset.list_absolute_path,
			batch_size = self.batch_sizes[1],
			new_width = self.infmt.new_width,
			new_height = self.infmt.new_height,
			root_folder = subset.root_folder,
			rand_skip = self.batch_sizes[1],
			shuffle = True
		)
		
		transform_param = dict(
			mirror = False,
			crop_size = self.infmt.crop_size,
		)
		
		if self.infmt.scale is not None:
			transform_param['scale'] = self.infmt.scale
		
		if self.infmt.mean_file is not None:
			transform_param['mean_file'] = self.infmt.mean_file
		else:
			transform_param['mean_value'] = self.infmt.mean_pixel
		
		n = NetSpec()
		n.data, n.label = L.ImageData(ntop=2, image_data_param=image_data_param, transform_param=transform_param) #, include=dict(phase=caffe.TEST))
		
		net = n.to_proto()
		net.name = self.name
		return net

	def train_tail(self, last_top):
		n = NetSpec()
		n.loss = L.SoftmaxWithLoss(bottom=[last_top, "label"])
		return n.to_proto()
		
	def val_tail(self, last_top):
		n = NetSpec()
		n.loss = L.SoftmaxWithLoss(bottom=[last_top, "label"])
		n.accuracy = L.Accuracy(bottom=[last_top, "label"]) #, include=dict(phase=caffe.TEST))		
		return n.to_proto()
		
	def test_head(self, subset):
		n = NetSpec()
		# test
		image_data_param = dict(
			source = subset.list_absolute_path,
			batch_size = self.batch_size,
			new_width = self.infmt.new_width,
			new_height = self.infmt.new_height,
			root_folder = subset.root_folder
		)
		
		transform_param = dict(
			crop_size = self.infmt.crop_size,
			# mean_value = self.infmt.mean_pixel,
		)
		
		if self.infmt.params['scale'] is not None:		
			transform_param['scale'] = self.infmt.scale
		
		if self.infmt.mean_file is not None:
			transform_param['mean_file'] = self.infmt.mean_file
		else:
			transform_param['mean_value'] = self.infmt.mean_pixel
		
		n.data, n.label = L.ImageData(ntop=2, image_data_param=image_data_param, transform_param=transform_param) #, include=dict(phase=caffe.TEST))
		
		net = n.to_proto()
		net.name = self.name
		return net
		
	def test_tail(self, last_top):
		n = NetSpec()
		n.accuracy = L.Accuracy(bottom=[last_top, "label"], include=dict(phase=caffe.TEST))
		return n.to_proto()
		
	# abstract method: must return a NetParameter object and last top name
	def body(self):
		raise NotImplementedError()
		
	def to_deploy_prototxt(self, optimize=True):
		if optimize: self.optimize_batch_size()
		
		net = self.deploy_head()
		tmp_net, last_top = self.body()
		net.MergeFrom(tmp_net)
		tmp_net = self.deploy_tail(last_top)
		net.MergeFrom(tmp_net)
		return str(net)
		
	def to_train_prototxt(self, subset):
		net = self.train_head(subset)
		tmp_net, last_top = self.body()
		net.MergeFrom(tmp_net)
		tmp_net = self.train_tail(last_top)
		net.MergeFrom(tmp_net)
		return str(net)
	
	def to_val_prototxt(self, subset):
		net = self.val_head(subset)
		tmp_net, last_top = self.body()
		net.MergeFrom(tmp_net)
		tmp_net = self.val_tail(last_top)
		net.MergeFrom(tmp_net)
		return str(net)
	
	def to_test_prototxt(self, subset):
	
		self.optimize_batch_size()
		
		num = subset.get_count()
		c = self.batch_size
		while num % c > 1:
			c = c - 1
		self.batch_size = c
		iters = num / c
		
		logging.debug("Using batch size x iters = {} x {} = {} images (out of {})".format(c, iters, c*iters, num))
		
		net = self.test_head(subset)
		tmp_net, last_top = self.body()
		net.MergeFrom(tmp_net)
		tmp_net = self.test_tail(last_top)
		net.MergeFrom(tmp_net)
		
		return str(net), iters

