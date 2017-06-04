#! /usr/bin/env python

import csv
import itertools
import numpy as np
import nltk
import time
import sys
import random
import operator
import io
import array
from datetime import datetime
from gru_theano import GRUTheano

SENTENCE_START_TOKEN = "SENTENCE_START"
SENTENCE_END_TOKEN = "SENTENCE_END"
UNKNOWN_TOKEN = "UNKNOWN_TOKEN"
CHECK_LEN = 3

def get_stock_module(filename='/home/lab/stock_demo/Rem/utils/data/stock_module.csv'):
    stock_module = {}
    with open(filename, 'rt') as f:
        reader = csv.reader(f)
        for row in reader:
            stock_module[row[1].decode("utf-8").lower()] = row[2]
    return stock_module

def load_data(filename="data/data_english.csv", vocabulary_size=2200, min_sent_characters=0):

    word_to_index = []
    index_to_word = []

    # Read the data and append SENTENCE_START and SENTENCE_END tokens
    csv.field_size_limit(500 * 1024 * 1024)
    print("Reading CSV file...")
    with open(filename, 'rt') as f:
        reader = csv.reader(f, skipinitialspace=True)
        reader.next()
        
        # Split full comments into sentences
        sentences = itertools.chain(*[nltk.sent_tokenize(x[0].decode("utf-8").lower()) for x in reader])
        # Filter sentences
        sentences = [s for s in sentences if len(s) >= min_sent_characters]
        sentences = [s for s in sentences if "http" not in s]
        # Append SENTENCE_START and SENTENCE_END
        sentences = ["%s %s %s" % (SENTENCE_START_TOKEN, x, SENTENCE_END_TOKEN) for x in sentences]
    
    sen_tmp = []
    target_set = []
    for sentence in sentences:
        if len(sentence.split(' '))<100 and len(sentence.split(' '))>10:
            sen_tmp.append(sentence)
            target_set.append(sentence)
    sentences = sen_tmp
    print("sentence[0] is")
    print(sentences[0])
    print("Parsed %d sentences." % (len(sentences)))
    # Tokenize the sentences into words
    tokenized_sentences = [nltk.word_tokenize(sent) for sent in sentences]

    # Count the word frequencies
    word_freq = nltk.FreqDist(itertools.chain(*tokenized_sentences))
    print("Found %d unique words tokens." % len(word_freq.items()))

    # Get the most common words and build index_to_word and word_to_index vectors
    vocab = sorted(word_freq.items(), key=lambda x: (x[1], x[0]), reverse=True)[:vocabulary_size-2]
    print("Using vocabulary size %d." % vocabulary_size)
    print("The least frequent word in our vocabulary is '%s' and appeared %d times." % (vocab[-1][0], vocab[-1][1]))

    sorted_vocab = sorted(vocab, key=operator.itemgetter(1))
    index_to_word = ["<MASK/>", UNKNOWN_TOKEN] + [x[0] for x in sorted_vocab]
    word_to_index = dict([(w, i) for i, w in enumerate(index_to_word)])
    
    
    target_sentence_set = []
    for target_sentence in target_set:
        target_sentence = target_sentence.split(' ')
        if len(target_sentence_set)>2:
            break
        if len(target_sentence)<10:
            continue
        del(target_sentence[-2])
        tmp = []
        tmp = [word_to_index[x] for x in target_sentence]
        target_sentence = tmp
        target_sentence_set.append(target_sentence)
    
    # Replace all words not in our vocabulary with the unknown token
    for i, sent in enumerate(tokenized_sentences):
        tokenized_sentences[i] = [w if w in word_to_index else UNKNOWN_TOKEN for w in sent]

    # Create the training data
    X_train = np.asarray([[word_to_index[w] for w in sent[:-1]] for sent in tokenized_sentences])
    y_train = np.asarray([[word_to_index[w] for w in sent[1:]] for sent in tokenized_sentences])

    return X_train, y_train, word_to_index, index_to_word, target_sentence, target_sentence_set


def train_with_sgd(model, X_train, y_train, learning_rate=0.001, nepoch=20, decay=0.9,
    callback_every=10000, callback=None):
    num_examples_seen = 0
    for epoch in range(nepoch):
        # For each training example...
        for i in np.random.permutation(len(y_train)):
            # One SGD step
            model.sgd_step(X_train[i], y_train[i], learning_rate, decay)
            num_examples_seen += 1
            # Optionally do callback
            if (callback and callback_every and num_examples_seen % callback_every == 0):
                callback(model, num_examples_seen)
    return model

def save_model_parameters_theano(model, outfile):
    np.savez(outfile,
        E=model.E.get_value(),
        U=model.U.get_value(),
        W=model.W.get_value(),
        V=model.V.get_value(),
        b=model.b.get_value(),
        c=model.c.get_value())
    print "Saved model parameters to %s." % outfile

def load_model_parameters_theano(path, modelClass=GRUTheano):
    npzfile = np.load(path)
    E, U, W, V, b, c = npzfile["E"], npzfile["U"], npzfile["W"], npzfile["V"], npzfile["b"], npzfile["c"]
    hidden_dim, word_dim = E.shape[0], E.shape[1]
    print "Building model model from %s with hidden_dim=%d word_dim=%d" % (path, hidden_dim, word_dim)
    sys.stdout.flush()
    model = modelClass(word_dim, hidden_dim=hidden_dim)
    model.E.set_value(E)
    model.U.set_value(U)
    model.W.set_value(W)
    model.V.set_value(V)
    model.b.set_value(b)
    model.c.set_value(c)
    return model

def gradient_check_theano(model, x, y, h=0.001, error_threshold=0.01):
    # Overwrite the bptt attribute. We need to backpropagate all the way to get the correct gradient
    model.bptt_truncate = 1000
    # Calculate the gradients using backprop
    bptt_gradients = model.bptt(x, y)
    # List of all parameters we want to chec.
    model_parameters = ['E', 'U', 'W', 'b', 'V', 'c']
    # Gradient check for each parameter
    for pidx, pname in enumerate(model_parameters):
        # Get the actual parameter value from the mode, e.g. model.W
        parameter_T = operator.attrgetter(pname)(model)
        parameter = parameter_T.get_value()
        print "Performing gradient check for parameter %s with size %d." % (pname, np.prod(parameter.shape))
        # Iterate over each element of the parameter matrix, e.g. (0,0), (0,1), ...
        it = np.nditer(parameter, flags=['multi_index'], op_flags=['readwrite'])
        while not it.finished:
            ix = it.multi_index
            # Save the original value so we can reset it later
            original_value = parameter[ix]
            # Estimate the gradient using (f(x+h) - f(x-h))/(2*h)
            parameter[ix] = original_value + h
            parameter_T.set_value(parameter)
            gradplus = model.calculate_total_loss([x],[y])
            parameter[ix] = original_value - h
            parameter_T.set_value(parameter)
            gradminus = model.calculate_total_loss([x],[y])
            estimated_gradient = (gradplus - gradminus)/(2*h)
            parameter[ix] = original_value
            parameter_T.set_value(parameter)
            # The gradient for this parameter calculated using backpropagation
            backprop_gradient = bptt_gradients[pidx][ix]
            # calculate The relative error: (|x - y|/(|x| + |y|))
            relative_error = np.abs(backprop_gradient - estimated_gradient)/(np.abs(backprop_gradient) + np.abs(estimated_gradient))
            # If the error is to large fail the gradient check
            if relative_error > error_threshold:
                print "Gradient Check ERROR: parameter=%s ix=%s" % (pname, ix)
                print "+h Loss: %f" % gradplus
                print "-h Loss: %f" % gradminus
                print "Estimated_gradient: %f" % estimated_gradient
                print "Backpropagation gradient: %f" % backprop_gradient
                print "Relative Error: %f" % relative_error
                return
            it.iternext()
        print "Gradient check for parameter %s passed." % (pname)


def print_sentence(s, index_to_word):
    sentence_str = [index_to_word[x] for x in s[1:-1]]
    print(" ".join(sentence_str))
    sys.stdout.flush()

def generate_sentence(model, index_to_word, word_to_index, min_length=5):
    # We start the sentence with the start token
    new_sentence = [word_to_index[SENTENCE_START_TOKEN]]
    # Repeat until we get an end token
    while not new_sentence[-1] == word_to_index[SENTENCE_END_TOKEN]:
        next_word_probs = model.predict(new_sentence)[-1]
        samples = np.random.multinomial(1, next_word_probs)
        sampled_word = np.argmax(samples)
        new_sentence.append(sampled_word)
        # Seomtimes we get stuck if the sentence becomes too long, e.g. "........" :(
        # And: We don't want sentences with UNKNOWN_TOKEN's
        if len(new_sentence) > 100 or sampled_word == word_to_index[UNKNOWN_TOKEN]:
            return None
    if len(new_sentence) < min_length:
        return None
    return new_sentence

def generate_sentences(model, n, index_to_word, word_to_index):
    for i in range(n):
        sent = None
        while not sent:
            sent = generate_sentence(model, index_to_word, word_to_index)
        print_sentence(sent, index_to_word)

def predict_sentence(model, index_to_word, word_to_index, target_sentence, stock_module):
    # We start the sentence with the start token
    new_sentence = [word_to_index[SENTENCE_START_TOKEN]]
    for sentence in target_sentence:
        new_sentence.append(sentence)
    predict_sentence = []
   
    for i in range(5):
        sampled_word = word_to_index[SENTENCE_END_TOKEN]
        while sampled_word == word_to_index[SENTENCE_END_TOKEN]:
            next_word_probs = model.predict(new_sentence)[-1]
            samples = np.random.multinomial(1, next_word_probs)
            sampled_word = np.argmax(samples)
        new_sentence.append(sampled_word)
        predict_sentence.append(sampled_word)
    print len(predict_sentence)
    return predict_sentence

def predict_sentence_with_modules(model, index_to_word, word_to_index, target_sentence, stock_module, modules):
    # We start the sentence with the start token
    new_sentence = [word_to_index[SENTENCE_START_TOKEN]]
    for sentence in target_sentence:
        new_sentence.append(sentence)
    predict_sentence = []
    for i in range(5):
        sampled_word = word_to_index[SENTENCE_END_TOKEN]
        while sampled_word == word_to_index[SENTENCE_END_TOKEN]:
            next_word_probs = model.predict(new_sentence)[-1]
            one_cnt = 0
            for index in range(len(index_to_word)):
                if stock_module.get(index_to_word[index]) is None:
                    continue
                if stock_module.get(index_to_word[index]).decode('utf-8') != modules[i]:
                    next_word_probs[index] = 0
                else:
                    one_cnt = one_cnt + 1
            print one_cnt
            arr = np.argsort(next_word_probs)[-one_cnt:][::-1]
            arr_probs = []
            for arr_i in arr:
                arr_probs.append(next_word_probs[arr_i])
            sum = np.sum(arr_probs)
            tmp = [x/sum for x in arr_probs]
            samples = np.random.multinomial(1, tmp)
            sampled_word = arr[np.argmax(samples)]
        new_sentence.append(sampled_word)
        predict_sentence.append(sampled_word)

    return predict_sentence

def check(sent, target):
    return len(set(sent[-CHECK_LEN:]) & set(target[-CHECK_LEN-1:]))>0

def predict_sentences(model, index_to_word, word_to_index, target_sentence_set, stock_module):
    cnt = 0
    i = 0
    for target_sentence in target_sentence_set:
        sent = None
        while not sent:
            sent = predict_sentence(model, index_to_word, word_to_index, target_sentence, stock_module)
        if check(sent, target_sentence):
            tmp = [index_to_word[x] for x in sent]
            print tmp
            tmp = [index_to_word[x] for x in target_sentence]
            print tmp
            cnt = cnt + 1
        i = i + 1
        print i
    print 'cnt is %d' % cnt