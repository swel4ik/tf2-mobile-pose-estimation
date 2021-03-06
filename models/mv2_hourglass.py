# Copyright 2019 Doyoung Gwak (tucan.dev@gmail.com)
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ======================
#-*- coding: utf-8 -*-

from tensorflow.keras import models
from tensorflow.keras import layers
from tensorflow.keras import regularizers

l2_regularizer_00004 = regularizers.l2(0.00004)

def _inverted_bottleneck(input, up_channel_rate, channels, is_subsample, kernel_size):
    if is_subsample:
        strides = (2, 2)
    else:
        strides = (1, 1)

    kernel_size = (kernel_size, kernel_size)

    # 1x1 conv2d
    x = layers.Conv2D(filters=up_channel_rate * input.shape[-1], kernel_size=(1, 1), strides=(1, 1), padding='SAME')(input)
    x = layers.BatchNormalization(momentum=0.999)(x)
    x = layers.ReLU(max_value=6)(x)

    # activation
    x = layers.ReLU()(x)

    # 3x3 separable_conv2d
    x = layers.DepthwiseConv2D(kernel_size=kernel_size, strides=strides, padding="SAME",
                               kernel_regularizer=l2_regularizer_00004)(x)
    # activation
    x = layers.ReLU()(x)

    # 1x1 conv2d
    x = layers.Conv2D(filters=channels, kernel_size=(1, 1), strides=(1, 1), padding='SAME')(x)
    x = layers.BatchNormalization(momentum=0.999)(x)
    x = layers.ReLU(max_value=6)(x)

    if input.shape[-1] == channels:
        x = input + x

    return x

def _hourglass_module(input, stage_index, number_of_keypoints):
    if stage_index == 0:
        return _inverted_bottleneck(input, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3), []
    else:
        # down sample
        x = layers.MaxPool2D(pool_size=(2, 2), strides=(2, 2), padding='SAME')(input)

        # block front
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)

        stage_index -= 1

        # block middle
        x, middle_layers = _hourglass_module(x, stage_index=stage_index, number_of_keypoints=number_of_keypoints)

        # block back
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=number_of_keypoints, is_subsample=False, kernel_size=3)

        # up sample
        upsampling_size = (2, 2)  # (x.shape[1] * 2, x.shape[2] * 2)
        x = layers.UpSampling2D(size=upsampling_size, interpolation='bilinear')(x)
        upsampling_layer = x

        # jump layer
        x = _inverted_bottleneck(input, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
        x = _inverted_bottleneck(x, up_channel_rate=6, channels=number_of_keypoints, is_subsample=False, kernel_size=3)
        jump_branch_layer = x

        # add
        x = upsampling_layer + jump_branch_layer

        middle_layers.append(x)

        return x, middle_layers

def build_mv2_hourglass_model(number_of_keypoints):
    hourglas_stage_num = 4
    input_shape = (192, 192, 3)  # h, w, c
    input = layers.Input(shape=input_shape)

    ## HEADER
    # cnn with regularizer
    x = layers.Conv2D(filters=16, kernel_size=(3, 3), strides=(2, 2), padding='SAME', kernel_regularizer=l2_regularizer_00004)(input)
    # batch norm
    x = layers.BatchNormalization(momentum=0.999)(x)
    # activation
    x = layers.ReLU(max_value=6)(x)

    # 128, 112
    x = _inverted_bottleneck(x, up_channel_rate=1, channels=16, is_subsample=False, kernel_size=3)
    x = _inverted_bottleneck(x, up_channel_rate=1, channels=16, is_subsample=False, kernel_size=3)

    # 64, 56
    x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=True, kernel_size=3)
    x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
    x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
    x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)
    x = _inverted_bottleneck(x, up_channel_rate=6, channels=24, is_subsample=False, kernel_size=3)


    captured_h, captured_w = int(x.shape[1]), int(x.shape[2])
    print(f"captured_h, captured_w: {captured_h}, {captured_w}")

    # HOURGLASS recursively
    # stage = 4
    #

    x, middle_output_layers = _hourglass_module(x, stage_index=hourglas_stage_num, number_of_keypoints=number_of_keypoints)

    print("before")
    for l in middle_output_layers:
        print(f"  l.shape: {l.shape}")

    for layer_index, middle_layer in enumerate(middle_output_layers):
        layer_stage = layer_index + 1
        h, w = middle_layer.shape[1], middle_layer.shape[2]
        if h == captured_h and w == captured_w:
            continue
        else:
            upsampling_size = (captured_h // h, captured_w // w)
            middle_output_layers[layer_index] = layers.UpSampling2D(size=upsampling_size, interpolation='bilinear')(middle_layer)

    print("after")
    for l in middle_output_layers:
        print(f"  l.shape: {l.shape}")

    model = models.Model(input, outputs=middle_output_layers)
    return model
