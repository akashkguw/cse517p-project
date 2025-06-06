import os
import re
import ast
from nltk.corpus import stopwords
from nltk.tokenize import RegexpTokenizer
import unicodedata

from sympy.ntheory.factor_ import smoothness

from utils.normalize import normalize_v2


#from utils.normalize import normalize
from utils.constants import MAX_NGRAM_SIZE, MAX_UNIGRAM_FALLBACK_SIZE, MAX_TOP_K
from collections import defaultdict, Counter
import pickle

# NOTE: this is just a raw n-gram model with frequencies.
# It does not have smoothening, probabilities, weights (for each level) etc. It is a very basic Ngram model
class NGramModel:

    def __init__(self, max_grams = MAX_NGRAM_SIZE):
        self.max_grams = MAX_NGRAM_SIZE

        # Captures all the models (Fallbacks, n-1 ... 1)
        self.models = {}

        # Top unigrams will help in identifying the top if we don't find next available characters.
        self.top_unigrams = []

        self.vocab = set()

    @staticmethod
    def normalize_conversations(conversation_str_list):
        """
        Extract 'value' texts using regex and normalize them.
        """
        normalized = []
        pattern = re.compile(r"'value'\s*:\s*'(.*?)'", re.DOTALL)

        for row in conversation_str_list:
            matches = pattern.findall(row)
            for text in matches:
                norm = normalize_v2(text)
                normalized.append({"normalized": norm})

        return normalized

    @classmethod
    def load_training_data(cls, train_dataset=None):
        """
        Normalizes and loads training data, splits each conversation into individual words.
        If no dataset is provided, it defaults to loading from the 'data/en.txt' file.
        """
        if train_dataset is None:
            return []
        
        try:
            train_conversations = train_dataset['conversations']
        except Exception as e:
            print(f"Error parsing conversations field: {e}")
            raise
        raw_normalized = cls.normalize_conversations(train_conversations)
        data = ''
        for i, conversation in enumerate(raw_normalized):
            data += ' ' + conversation['normalized']
            if i % 1000 == 0:
                print(f"convo #{i}")
        print("Normalized data preview:", data[:200])
        return data

    @classmethod
    def load_dev_data(cls, dev_dataset=None):
        """
        Normalizes and loads dev data, splits each conversation into individual words.
        """
        if dev_dataset is None:
            return []
        
        try:
            dev_conversations = dev_dataset['conversations']
        except Exception as e:
            print(f"Error parsing conversations field: {e}")
            raise
        return cls.normalize_conversations(dev_conversations)

    @classmethod
    def load_test_data(cls, fname):
        data = []
        with open(fname) as f:
            for line in f:
                inp = line[:-1]
                data.append(inp)
        return data

    @classmethod
    def write_pred(cls, preds, fname):
        with open(fname, 'wt') as f:
            for p in preds:
                f.write('{}\n'.format(p))

    '''
    Trains character level n-gram model from raw text.
    Builds models for all n from 1 to max_grams. Example 1-gram, 2-gram ... nGram.
    
    Example if max_grams = 3 for context "hello ":
    1 gram: context '', next_char = h
    2 gram: context 'h', next_char = e
    3 gram: context 'he', next_char = l
    
    Optimizations that can be done:
    1. We can do a word level n-gram and do a mix and match whenever we encounter a blank space (akashkg@)
    
    TODO: Try moving this to its own python script for better management.
    '''
    def run_train(self, data, work_dir):

        # Basic normalization only
        # TODO: Do de-tokenization of the data - the data set always show ' ' after ' character.
        # DATA IS ALREADY NORMALIZED, keeping in case we need to compare training on data/en.txt
        # data =  normalize(raw_data)

        # Build the n-gram model upto max_grams - n
        # n = 1, 2... max_grams

        self.vocab = set(data)

        for n in range(1, self.max_grams + 1):

            # create the NGramTable
            self.models[n] = defaultdict(Counter)
            for i in range(len(data) - n):

                # Extract the context and the next character
                '''
                For internal & future reference:
                
                    n = 3, data = "hello "
                    at i - 0, context = he, next char = l
                    at i = 1, context = el, next char = l
                    at i = 2, context = ll, next char = 0
                    
                Also, if n is 0 (unigram), we default context to '', we look at the probability of each character.
                '''
                context = data[i:i + n - 1] if n > 1 else ''
                next_char = data[i + n - 1]

                # Updating the count of next char following this context
                self.models[n][context][next_char] += 1

        # Identify top unigrams - ignores frequency
        all_chars = Counter(data)
        self.top_unigrams = [char for char, _ in all_chars.most_common(MAX_UNIGRAM_FALLBACK_SIZE)]
        print("Top unigrams: ", self.top_unigrams)

    def run_pred(self, data):
        # your code here
        preds = []
            
        for context in data:
            preds.append(self.predict_next_chars(context))
            print("Context: ", context)
            print("Predicted: ", preds[-1])
        
        return preds

    def predict_next_chars(self, context, top_k=MAX_TOP_K):
        candidates = []
        seen = set()
        context = normalize_v2(context)

        # Iterate from the max_grams to lower ngrams if context not found n ... 3, 2, 1
        for n in range(self.max_grams, 0, -1):
            # Returns the last (n-1) characters of the context; '' for unigram.
            ctx = context[-(n - 1):] if n > 1 else ''  # Context is a list
            # ctx = context[-(n - 1):] if n > 1 else ''
            model = self.models.get(n, {})
            dist = model.get(ctx, {})

            if not dist:
                continue

            total = sum(dist.values())
            V = len(self.vocab)

            smoothness = {
                char: (dist.get(char, 0) + 1) / (total / V)
                for char in self.vocab
            }

            sorted_chars = sorted(smoothness.items(), key=lambda x: x[1], reverse=True)
            for char, _ in sorted_chars:
                if char not in seen:
                    candidates.append(char)
                    seen.add(char)
                # if the condition is met.
                if len(candidates) >= top_k:
                    return ''.join(candidates[:top_k])

        # Fallback to top unigrams
        # In this case we would have had lesser characters than K
        for char in self.top_unigrams:
            if char not in seen:
                candidates.append(char)
            if len(candidates) >= top_k:
                break

        return ''.join(candidates[:top_k])

    def save(self, work_dir):

        with open(os.path.join(work_dir, 'model.sda'), 'wb') as f:
            pickle.dump({
                "max_n": self.max_grams,
                "models": self.models,
                "top_unigrams": self.top_unigrams,
                "vocab": list(self.vocab)
            }, f)

    @classmethod
    def load(cls, work_dir):
        # your code here
        # this particular model has nothing to load, but for demonstration purposes we will load a blank file
        with open(os.path.join(work_dir, 'model.sda'), 'rb') as f:
            obj = pickle.load(f)
        model = cls(max_grams=obj['max_n'])
        model.models = obj['models']
        model.top_unigrams = obj['top_unigrams']
        model.vocab = set(obj['vocab'])
        return model