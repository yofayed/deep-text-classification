import logging
from keras.layers.recurrent import LSTM, GRU
from keras.models import Sequential, model_from_json, Graph
from keras.layers.core import Dense, Dropout, MaxoutDense, Activation
from keras.layers.advanced_activations import PReLU
from keras.callbacks import EarlyStopping, ModelCheckpoint, Callback
from keras.optimizers import SGD

from cnn.layers.convolutions import *
from cnn.layers.embeddings import *

import numpy as np
import cPickle as pickle

LOGGER_PREFIX = ' %s'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log(msg, logger=logger):
    logger.info(LOGGER_PREFIX % msg)


if __name__ == '__main__':

    

    WV_FILE = './data/wv/IMDB-GloVe-100dim-glovebox.pkl'
    MODEL_FILE = './test-model.h5'

    # -- load in all the data
    train, test = {}, {}

    log('Loading training data')

    train['text'] = np.load('IMDB_train_glove_X.npy')
    train['labels'] = np.load('IMDB_train_glove_y.npy')

    log('Shuffling training data')
    shuff = range(train['text'].shape[0])
    np.random.shuffle(shuff)

    train['text'], train['labels'] = train['text'][shuff], train['labels'][shuff]

    # -- flatten across paragraph dimension, will later be reconstructed in the embedding
    train['text'] = train['text'].reshape(train['text'].shape[0], -1)

    weights = 1.0 * (train['text'] > 0)

    del shuff

    log('Loading testing data')

    # -- testing data
    test['text'] = np.load('IMDB_test_glove_X.npy')
    test['text'] = test['text'].reshape(test['text'].shape[0], -1)
    test['labels'] = np.load('IMDB_test_glove_y.npy')

    log('Loading IMDB trained word vectors')
    gb = pickle.load(open(WV_FILE, 'rb'))
    
    WV_PARAMS = {
        'floating_wv' :
        {
            'vocab_size' : gb.W.shape[0],
            'init' : gb.W,
            'fixed' : False
        }
    }

    NGRAMS = [2, 3, 4, 5, 7, 9]
    NFILTERS = 32
    SENTENCE_LENGTH = 50
    PARAGRAPH_LENGTH = 50

    log('Making graph model')
    graph = Graph()
    graph.add_input(name='text', input_shape=(-1, ), dtype='int')

    log('Making embedding')
    
    embed = paragraph_embedding(PARAGRAPH_LENGTH, WV_PARAMS, WV_PARAMS['floating_wv']['init'].shape[1])

    graph.add_node(embed, name='embedding', input='text')

    # graph.add_node(Embedding(WV_PARAMS['floating_wv']['vocab_size'], ), name='embedding', input='text')

    log('Adding convolved n-grams')
    # for n in [4, 5]:
    for n in NGRAMS:
        graph.add_node(
            TimeDistributedConvolution2D(NFILTERS, n, WV_PARAMS['floating_wv']['init'].shape[1], activation='relu'), 
            name='conv{}gram'.format(n), input='embedding')

        graph.add_node(
            TimeDistributedMaxPooling2D(pool_size=(SENTENCE_LENGTH - n + 1, 1)),
            name='maxpool{}gram'.format(n), input='conv{}gram'.format(n))

        graph.add_node(
            Dropout(0.7),
            name='dropout{}gram'.format(n), input='maxpool{}gram'.format(n))    

        graph.add_node(
            TimeDistributedFlatten(), 
            name='flatten{}gram'.format(n), input='dropout{}gram'.format(n))

    log('Adding bi-directional GRU')
    graph.add_node(GRU(25), name='gru_forwards', inputs=['flatten{}gram'.format(n) for n in NGRAMS], concat_axis=-1)
    graph.add_node(GRU(25, go_backwards=True), name='gru_backwards', inputs=['flatten{}gram'.format(n) for n in NGRAMS], concat_axis=-1)
    # graph.add_node(GRU(16), name='gru', input='flatten4gram')

    graph.add_node(Dropout(0.5), name='gru_dropout', inputs=['gru_forwards', 'gru_backwards'])

    graph.add_node(Dense(1, activation='sigmoid'), name='probability', input='gru_dropout')

    graph.add_output(name='prediction', input='probability')

    log('Compiling model (Veuillez patienter)...')
    sgd = SGD(lr=0.01, momentum=0.8, decay=0.0001, nesterov=True)
    graph.compile(sgd, {'prediction': 'binary_crossentropy'})

    log('Fitting! Hit CTRL-C to stop early...')
    try:
        history = graph.fit(
            {'text': train['text'], 'prediction': train['labels']}, 
            validation_split=0.35, batch_size=28, nb_epoch=100, 
            verbose=2, # -- for logging purposes
            sample_weight = {'prediction' : weights}, callbacks = 
                   [
                       EarlyStopping(verbose=True, patience=30, monitor='val_loss'),
                       ModelCheckpoint(MODEL_FILE, monitor='val_loss', verbose=True, save_best_only=True)
                   ]
           )
    except KeyboardInterrupt:
        log('Training stopped early!')

    log('Loading best weights...')
    graph.load_weights(MODEL_FILE)

    log('getting predictions on the test set')
    yhat = graph.predict({'text': test['text']}, verbose=True, batch_size=50)

    acc = ((yhat['prediction'].ravel() > 0.5) == (test['labels'] > 0.5)).mean()

    log('Test set accuracy of {}%.'.format(acc * 100.0))
    log('Test set error of {}%. Exiting...'.format((1 - acc) * 100.0))





