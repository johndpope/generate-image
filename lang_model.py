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
from layers.lstm_no_peephole_layer import LSTMLayer
from layers.hidden_layer import HiddenLayer


def zeros(shape, type=theano.config.floatX):
    return theano.shared(np.zeros(shape).astype(type))

def to_one_hot(y, bs, classes):
#    y = theano.printing.Print('yshape')(y)
    tmp = T.zeros((bs, classes))
    return T.set_subtensor(tmp[T.arange(bs), y], 1)


class LanguageModel(Model):
    def __init__(self, bs, K, N, m):
        # builds a bidirectional LSTM to create
        # a m-dimensional hidden state for the given
        # sequence of lenth N with vocab size K
        self.K = K
        self.N = N
        self.m = m
        self.bs = bs
        self.forward_in = HiddenLayer(input_size=K, hidden_size=m*4//2,
                                      batch_size=bs, name='forward-lstm-in')
        self.forward_lstm = LSTMLayer(hidden_size=m//2, 
                                      activation=T.tanh, 
                                      batch_size=bs,
                                      dropout=0.0,
                                      name='forward-lstm')
        
        self.backward_in = HiddenLayer(input_size=K, hidden_size=m*4//2,
                                       batch_size=bs, name='backward-lstm-in')
        self.backward_lstm = LSTMLayer(hidden_size=m//2, 
                                       activation=T.tanh, 
                                       batch_size=bs,
                                       dropout=0.0,
                                       name='backward-lstm')
        
    def run(self, y):
        # y comes in as shape batch X total_seq
        y = y.transpose([1,0])
        # y is of shape seq X batch and of type 'int'
        # y needs to be 1-hot encoded, but this is more
        # easily done in the step function

        # reverse each example of y (not the batches, just the variables)
        y_rev = y[::-1, :]

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
        # this needs to be aligned so that [4,13,45,3,X, X, X]
        # and                              [0,0, 0, 3,45,13,4]
        # concatenate correctly to         [4/3,13/25,45/13,3/4,X,X,X]

        # stores the indices of the string
        b_indx = zeros((self.N, self.bs), int)
        # stores the last-set index
        c = zeros((self.bs,), int)
        # This loop creates an array that can be used to
        # map hb to hf with the proper alignment
        for i in range(self.N):
            # if this part of y_rev is 0, ignore
            # else, get the current index
            indx = T.switch(T.neq(y_rev[i,:], 0), i, 0)
            # set b_indx to be the current indx if this is
            # a valid part of the string
            b_indx = T.set_subtensor(b_indx[c,T.arange(self.bs)], indx)
            
            # increment those that were used
            inc = T.switch(T.neq(y_rev[i,:], 0), 1, 0)
            c  = c + inc
            
        # the magic that gets hb to align with hf
        # it takes hb, uses the aligning indices and grabs those on the
        # diagonal as the elements we are interested in. This results in
        # essentially "shifting" the first non-zero element of hb
        # to the front of the list, for each sample in the batch
        h_b_aligned = hb[b_indx][:,T.arange(self.bs),T.arange(self.bs)]
        # concatenate them together. Now everything is aligned, as it should be!
        h_lang = T.concatenate([hf, h_b_aligned], axis=2)

        # axis 0 -> N
        # axis 1 -> batch
        # axis 2 -> m
        return h_lang

    def step(self, y_m, yb_m, hf, cf, hb, cb):
        # y_m/yb_m are what shape? should be batch_size (x 1)
        print y_m.ndim
        # one-hot encode y,yb (NEED TO SAVE PREVIOUS VALUES FOR MASKING!!!)
        y = to_one_hot(y_m, self.bs, self.K)
        yb = to_one_hot(yb_m, self.bs, self.K)

        # get forward and backward inputs values
        y_f_in = self.forward_in.run(y)
        y_b_in = self.backward_in.run(yb)
        
        # run forward and backward LSTMs
        hf_t,cf_t = self.forward_lstm.run(y_f_in, hf, cf)
        hb_t,cb_t = self.backward_lstm.run(y_b_in, hb, cb)

        # but only if y/yb is not 0 (apply mask)
        mask_y = y_m.reshape((self.bs, 1))#.repeat(self.m//2, axis=1) # these lines *shouldnt* be needed...
        mask_yb = yb_m.reshape((self.bs, 1))#.repeat(self.m//2, axis=1)
        hf = T.switch(T.neq(mask_y, 0), hf_t, hf)
        cf = T.switch(T.neq(mask_y, 0), cf_t, cf)
        # and backward
        hb = T.switch(T.neq(mask_yb, 0), hb_t, hb)
        cb = T.switch(T.neq(mask_yb, 0), cb_t, cb)

        # return the new values
        return hf,cf,hb,cb

    @property
    def params(self):
        return self.forward_in.params+self.forward_lstm.params+self.backward_in.params+\
            self.backward_lstm.params
