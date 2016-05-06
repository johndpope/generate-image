from __future__ import division
import theano
from theano import tensor as T
import numpy as np
from layers.hidden_layer import HiddenLayer
import activations as act

class ReadLayer(object):

    def __init__(self, batch_size, N, channels, image_width, image_height, input_hidden_size,
                 use_dx_dy=False, name='', test=False, use_gpu=True, device='gpu', use_gamma=True):
        """
        Read Layer from DRAW paper
        """

        self.batch_size = batch_size
        self.use_dx_dy = use_dx_dy
        self.N = N
        self.channels = channels
        self.width = image_width
        self.height = image_height
        self.name = name
        self.input_hidden_size = input_hidden_size
        self.test = test
        self.output_shape = [batch_size, channels, N, N]
        self.use_gpu = use_gpu
        self.use_gamma = use_gamma
        self.device = device

        self.init_params()

    def load_pretrained(self, v, i):
        return i

    def init_params(self):
        self.transform_hidden = HiddenLayer(input_size=self.input_hidden_size,
                                            hidden_size=5+self.use_dx_dy,
                                            batch_size=self.batch_size,
                                            activation=act.Identity,
                                            device=self.device,
                                            name='Read.Transform.'+self.name)
    def batched_dot(self, A, B):
        if self.use_gpu:
            return theano.sandbox.cuda.blas.batched_dot(A, B)
        else:
            return T.batched_dot(A,B)
#        C = A.dimshuffle([0,1,2,'x']) * B.dimshuffle([0,'x',1,2])
#        return C.sum(axis=-2)

    def get_params(self, h):
        hidden = self.transform_hidden.run(h)
        
        gx = (hidden[:,0]+1)*0.5 * self.width
        gy = (hidden[:,1]+1)*0.5 * self.height
        s2 = T.exp(hidden[:,3]/2.0)
        if self.use_gamma:
            g = T.exp(hidden[:,4]).dimshuffle(0,'x')
        else:
            g = T.exp(hidden[:,4]).dimshuffle(0,'x')
            g = g/g
        if self.use_dx_dy:
            dx = (self.width-1.0) / (self.N-1.0) *  T.exp(hidden[:,2])
            dy = (self.height-1.0) / (self.N-1.0) *  T.exp(hidden[:,5])
        else:
            dx = dy = ((max(self.width,self.height)-1.0) / (self.N-1.0) * T.exp(hidden[:,2]))
        return gx,gy,dx,dy,s2,g

    def get_params_test(self, h):
        return h[:,0], h[:,1], h[:,2], h[:,5], h[:,3], h[:,4].dimshuffle(0,'x')

    def run(self, images, h):#, error_images, h):
        channels = self.channels#images.shape[1]
        if not self.test:
            gx,gy,dx,dy,s2,g = self.get_params(h)
        else:
            gx,gy,dx,dy,s2,g = self.get_params_test(h)

        # how to handle variable sized input images? (mask??)
        I = images.reshape((self.batch_size*self.channels, self.height, self.width))

        muX = gx.dimshuffle([0,'x']) + dx.dimshuffle([0,'x']) * (T.arange(self.N).astype(theano.config.floatX) - self.N/2 - 0.5)
        muY = gy.dimshuffle([0,'x']) + dy.dimshuffle([0,'x']) * (T.arange(self.N).astype(theano.config.floatX) - self.N/2 - 0.5)

        a = T.arange(self.width).astype(theano.config.floatX)
        b = T.arange(self.height).astype(theano.config.floatX)

        Fx = T.exp(-(a-muX.dimshuffle([0,1,'x']))**2 / 2. / s2.dimshuffle([0,'x','x'])**2)
        Fy = T.exp(-(b-muY.dimshuffle([0,1,'x']))**2 / 2. / s2.dimshuffle([0,'x','x'])**2)

        Fx = Fx / (Fx.sum(axis=-1).dimshuffle([0,1,'x']) + 1e-4)
        Fy = Fy / (Fy.sum(axis=-1).dimshuffle([0,1,'x']) + 1e-4)

        self.Fx = T.repeat(Fx, channels, axis=0)
        self.Fy = T.repeat(Fy, channels, axis=0)

        self.fint = self.batched_dot(self.Fy, I)
#        self.efint = T.dot(self.Fx, error_images)
        self.fim = self.batched_dot(self.fint, self.Fx.transpose([0,2,1])).reshape(
            (self.batch_size, self.channels*self.N*self.N))
#        self.feim = T.dot(self.efint, self.Fy.transpose([0,2,1])).reshape(
#            (self.batch_size, channels,self.N,self.N))
        return g * self.fim, (gx, gy, dx, dy, self.fint)#$T.concatenate([self.fim, self.feim], axis=1)

    @property
    def params(self):
        return [param for param in self.transform_hidden.params]

    @params.setter
    def params(self, params):
        self.transform_hidden.params = params

    def print_layer(self):
        v = '--------------------\n'
        v += 'Read Layer '+self.name+'\n'
        v += 'Input Shape: '+str((self.width, self.height))+'\n'
        return v + 'Output Shape: '+str((self.N, self.N))+'\n'
