from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import hashlib
import os.path
import random

import numpy as np
from skimage import color, io
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf

from tensorflow.python.platform import gfile
from tensorflow.python.util import compat

from tensorflow.python.framework import dtypes
from tensorflow.python.framework.ops import convert_to_tensor


from utils.oper_utils2 import trsf_proba_to_binary, \
    imgs_to_grayscale, invert_imgs


MAX_NUM_WAVS_PER_CLASS = 2**27 - 1  # ~134M
RANDOM_SEED = 888


def which_set(filename, validation_percentage):
    """Determines which data partition the file should belong to.

    Args:
      filename: File path of the data sample.
      validation_percentage: How much of the data set to use for validation.
    Returns:
      String, one of 'training', 'validation'.
    """
    base_name = os.path.basename(filename)
    hash_name_hashed = hashlib.sha1(compat.as_bytes(base_name)).hexdigest()
    percentage_hash = ((int(hash_name_hashed, 16) % (MAX_NUM_WAVS_PER_CLASS + 1)) *
                       (100.0 / MAX_NUM_WAVS_PER_CLASS))
    if percentage_hash < validation_percentage:
        result = 'validation'
    else:
        result = 'training'
    return result


class Data(object):
    def __init__(self, data_dir, validation_percentage):
        self.data_dir = data_dir
        self._prepare_data_index(validation_percentage)


    def get_data(self, mode):
        return self.data_index[mode]


    def get_size(self, mode):
        """Calculates the number of samples in the _dataset partition.
        Args:
          mode: Which partition, must be 'training', 'validation', or 'testing'.
        Returns:
          Number of samples in the partition.
        """
        return len(self.data_index[mode])


    def _prepare_data_index(self, validation_percentage):
        # Make sure the shuffling and picking of unknowns is deterministic.
        random.seed(RANDOM_SEED)
        self.data_index = {'validation': [], 'training': []}
        data_paths = os.listdir(self.data_dir)
        for img_path in data_paths:
            set_index = which_set(img_path, validation_percentage)
            self.data_index[set_index].append({'image': img_path})

        # Make sure the ordering is random.
        for set_index in ['validation', 'training']:
            random.shuffle(self.data_index[set_index])


class DataLoader(object):

    def __init__(self, data_dir, data, img_size, label_size, batch_size, shuffle=True):

        self.data_size = len(data)
        images, labels = self._get_data(data_dir, data)
        self.img_size = img_size
        self.label_size = label_size

        # create _dataset, Creating a source
        dataset = tf.data.Dataset.from_tensor_slices((images, labels))

        # shuffle the first `buffer_size` elements of the _dataset
        #  Make sure to call tf.data.Dataset.shuffle() before applying the heavy transformations
        # (like reading the images, processing them, batching...).
        if shuffle:
            dataset = dataset.shuffle(buffer_size= 100 * batch_size)

        # distinguish between train/infer. when calling the parsing functions
        # transform to images, preprocess, repeat, batch...
        dataset = dataset.map(self._parse_function, num_parallel_calls=8)

        dataset = dataset.prefetch(buffer_size = 10 * batch_size)

        # create a new _dataset with batches of images
        dataset = dataset.batch(batch_size)

        self.dataset = dataset


    def _get_data(self, data_dir, data):
        image_paths = np.array(data)
        mask_paths = np.array(data)

        for idx, image_path in enumerate(image_paths):
            img_dir = os.path.join(data_dir, image_path['image'], 'images')
            mask_dir = os.path.join(data_dir, image_path['image'], 'gt_mask')

            img = os.listdir(img_dir)
            mask = os.listdir(mask_dir)

            image_paths[idx] = os.path.join(img_dir, img[0])
            mask_paths[idx] = os.path.join(mask_dir, mask[0])

        # convert lists to TF tensor
        image_paths = convert_to_tensor(image_paths, dtype=dtypes.string)
        mask_paths = convert_to_tensor(mask_paths, dtype=dtypes.string)

        return image_paths, mask_paths


    def _parse_function(self, image_file, label_file):
        image_string = tf.read_file(image_file)
        image_decoded = tf.image.decode_png(image_string, channels=3)
        image_resized = tf.image.resize_images(image_decoded,
                                               [self.img_size, self.img_size],
                                               method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
        image = tf.image.convert_image_dtype(image_resized, dtype=tf.float32)
        # Finally, rescale to [-1,1] instead of [0, 1)
        # image = tf.subtract(image, 0.5)
        # image = tf.multiply(image, 2.0)
        # image = tf.image.rgb_to_grayscale(image)


        label_string = tf.read_file(label_file)
        label_decoded = tf.image.decode_png(label_string, channels=1)
        label_resized = tf.image.resize_images(label_decoded,
                                               [self.label_size, self.label_size],
                                               method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
        label = tf.image.convert_image_dtype(label_resized, dtype=tf.float32)
        # Finally, rescale to [-1,1] instead of [0, 1)
        # label = tf.subtract(label, 0.5)
        # label = tf.multiply(label, 2.0)

        return image, label