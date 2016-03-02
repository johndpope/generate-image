# ========= STD Libs  ============
from __future__ import division
import logging

# ========= Theano/npy ===========
import theano
import theano.tensor as T
from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams
import numpy as np

# ========= Tools  ==============
from model import Model

# ========= Layers  ==============
import layers.activations as act
from layers.dropout import dropout
from layers.lstm2_layer import LSTMLayer
from layer.hidden_layer import HiddenLayer


def zeros(shape):
    return theano.shared(np.zeros(shape).astype(theano.config.floatX))

def to_one_hot(y, classes):
    tmp = T.zeros((y.shape[0], classes))
    return T.set_subtensor(tmp[T.arange(y.shape[0]), y], 1)


class LanguageModel(Model):
    def __init__(self, bs, K, N, m):
        # builds a bidirectional LSTM to create
        # a m-dimensional hidden state for the given
        # sequence of lenth N with vocab size
        # K
        self.K = K
        self.N = N
        self.m = m
        self.bs = bs
        self.forward_in = HiddenLayer(input_size=K, hidden_size=m*4,
                                      batch_size=bs, name='forward-lstm-in')
        self.forward_lstm = LSTMLayer(hidden_size=m, 
                                      activation=T.tanh, 
                                      batch_size=bs,
                                      dropout=0.0,
                                      name='forward-lstm')
        
        self.backward_in = HiddenLayer(input_size=K, hidden_size=m*4,
                                       batch_size=bs, name='backward-lstm-in')
        self.backward_lstm = LSTMLayer(hidden_size=m, 
                                       activation=T.tanh, 
                                       batch_size=bs,
                                       dropout=0.0,
                                       name='backward-lstm')
        
    def run(self, y):
        # y is of shape seq X batch X 1 and of type 'int'
        # y needs to be 1-hot encoded, but this is more
        # easily done in the step function

        # reverse each example of y (not the batches, just the variables)
        y_rev = y[:, ::-1, :]

        # get initial values for LSTMs
        hf, cf = self.forward_lstm.get_initial_hidden
        hb, cb = self.backward_lstm.get_initial_hidden

        # setup initial values for scan
        outputs_info = [dict(initial=hf, taps=[-1]), # hf
                        dict(initial=cf, taps=[-1]), # cf
                        dict(initial=hb, taps=[-1]), # cb
                        dict(initial=cb, taps=[-1])] # cb
                        
        # run LSTM loop
        [hf,cf,hb,cb], _ = theano.scan(fn=self.step,
                                       sequences=[y,y_rev],
                                       outputs_info=outputs_info,
                                       n_steps=self.N)

        # return forward and backward concatenated
        # this needs to be aligned so that [4,13,45,3,0, 0, 0]
        # and                              [0,0, 0, 3,45,13,4]
        # concatenate correctly to         [4/3,13/25,45/13,3/4,0,0,0]


        h_lang = zeros((self.N, self.batch_size, self.m))
        b_indx = zeros((self.N, self.batch_size)).astype(int)
        c = zeros((self.batch_size)).astype(int)
        for i in range(self.N):
            # if this part of y_rev is 0, ignore
            # else, get the current index
            indx = T.switch(T.neq(y_rev[i], 0), i, 0)
            b_indx = T.set_subtensor(b_indx[indx, :], indx)
            
            # increment those that were used
            inc = T.switch(T.neq(y_rev[i], 0), 1, 0)
            c  = c + inc

        h_b_aligned = hb[b_indx]

        # axis 0 -> N
        # axis 1 -> batch
        # axis 2 -> m
        return h_lang[::-1]

    def step(self, y_m, yb_m, hf, cf, hb, cb):
        # one-hot encode y,yb (NEED TO SAVE PREVIOUS VALUES FOR MASKING!!!)
        y = to_one_hot(y_m, self.K)
        yb = to_one_hot(yb_m, self.K)

        # get forward and backward inputs values
        y_f_in = self.forward_in.run(y)
        y_b_in = self.backward_in.run(yb)
        
        # run forward and backward LSTMs
        hf_t,cf_t = self.forward_lstm.run(y_f_in, hf, cf)
        hb_t,cb_t = self.backward_lstm.run(y_b_in, hb, cb)

        # but only if y/yb is not 0 (apply mask)
        hf = T.switch(T.neq(y_m, 0), hf_t, hf)
        cf = T.switch(T.neq(y_m, 0), cf_t, cf)
        # and backward
        hb = T.switch(T.neq(yb_m, 0), hb_t, hb)
        cb = T.switch(T.neq(yb_m, 0), cb_t, cb)

        # return the new values
        return hf,cf,hb,cb

    @property
    def params(self):
        return self.forward_in.params+self.forward_lstm.params+self.backward_in.params+\
            self.backward_lstm.params
