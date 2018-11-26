# -*- coding: utf-8 -*-

import chainer
from chainer import cuda, serializers

import csv
import sys
import time
import random
import copy
import math
import os
import numpy as np
import configparser
from argparse import ArgumentParser
from os import path as pt
import skimage.io as io
from skimage import morphology
from skimage.morphology import watershed
from scipy import ndimage

sys.path.append(os.getcwd())
from src.lib.trainer import NSNTrainer, NDNTrainer
from src.lib.utils import createOpbase
from src.lib.utils import create_dataset_parser, create_model_parser, create_runtime_parser
from src.lib.utils import print_args
from src.lib.utils import get_model
from src.tools.test_nsn import TestNSN
from src.tools.test_ndn import TestNDN
from src.lib.model import Model_L2, Model_L3, Model_L4

def main():

    start_time = time.time()
    ap = ArgumentParser(description='python qca_net.py')
    ap.add_argument('--indir', '-i', nargs='?', default='../images/example_input', help='Specify input files directory : Phase contrast cell images in gray scale')
    ap.add_argument('--outdir', '-o', nargs='?', default='result_qca_net', help='Specify output files directory for create segmentation, labeling & classification images')
    ap.add_argument('--model_nsn', '-ms', nargs='?', default='models/p96/nsn/learned_nsn_dice_v1.npz', help='Specify loading file path of Learned Segmentation Model')
    ap.add_argument('--model_ndn', '-md', nargs='?', default='models/p96/ndn/learned_ndn_dice_v1.npz', help='Specify loading file path of Learned Detection Model')
    ap.add_argument('--gpu', '-g', type=int, default=-1, help='Specify GPU ID (negative value indicates CPU)')
    ap.add_argument('--patchsize_seg', '-ps', type=int, default=96, help='Specify pixel size of Segmentation Patch')
    ap.add_argument('--patchsize_det', '-pd', type=int, default=96, help='Specify pixel size of Detection Patch')
    ap.add_argument('--stride_seg', '-ss', type=int, default=48, help='Specify pixel size of Segmentation Stride')
    ap.add_argument('--stride_det', '-sd', type=int, default=48, help='Specify pixel size of Detection Stride')
    ap.add_argument('--delete', '-d', type=int, default=0, help='Specify Pixel Size of Delete Region for Cell Detection Model')
    ap.add_argument('--scaling_seg', action='store_true', help='Specify Image-wise Scaling Flag in Detection Phase')
    ap.add_argument('--scaling_det', action='store_true', help='Specify Image-wise Scaling Flag in Classification Phase')
    ap.add_argument('--resolution_x', '-x', type=float, default=1.0, help='Specify microscope resolution of x axis (default=1.0)')
    ap.add_argument('--resolution_y', '-y', type=float, default=1.0, help='Specify microscope resolution of y axis (default=1.0)')
    ap.add_argument('--resolution_z', '-z', type=float, default=2.18, help='Specify microscope resolution of z axis (default=2.18)')
    ap.add_argument('--ndim', type=int, default=3,
                        help='Dimensions of input / convolution kernel')
    ap.add_argument('--lossfun', type=str, default='softmax_dice_loss',
                        help='Specify Loss function')
    ap.add_argument('--ch_base', type=int, default=16,
                        help='Number of base channels (to control total memory and segmentor performance)')
    # ap.add_argument('--ch_base_ndn', type=int, default=12,
    #                     help='Number of base channels (to control total memory and segmentor performance)')
    ap.add_argument('--ch_out', type=int, default=2,
                        help='Number of channels for output (label)')
    ap.add_argument('--class_weight', default='(1, 1)',
                        help='Specify class weight with softmax corss entropy')
    ap.add_argument('--model', default='NSN',
                        help='Specify class weight with softmax corss entropy')



    args = ap.parse_args()
    argvs = sys.argv
    psep = '/'

    opbase = createOpbase(args.outdir)
    wsbase = 'WatershedSegmentationImages'
    if not (pt.exists(opbase + psep + wsbase)):
        os.mkdir(opbase + psep + wsbase)


    print('Patch Size of Segmentation: {}'.format(args.patchsize_seg))
    print('Patch Size of Detection: {}'.format(args.patchsize_det))
    print('Delete Voxel Size of Detection Region: {}'.format(args.delete))
    print('Scaling Image in Segmentation Phase: {}'.format(args.scaling_seg))
    print('Scaling Image in Detection Phase: {}'.format(args.scaling_det))
    with open(opbase + psep + 'result.txt', 'w') as f:
        f.write('python ' + ' '.join(argvs) + '\n')
        f.write('[Properties of parameter]\n')
        f.write('Output Directory: {}\n'.format(opbase))
        f.write('Patch Size of Segmentation: {}\n'.format(args.patchsize_seg))
        f.write('Patch Size of Detection: {}\n'.format(args.patchsize_det))
        f.write('Delete Pixel Size of Detection Region: {}\n'.format(args.delete))
        f.write('Scaling Image in Segmentation Phase: {}\n'.format(args.scaling_seg))
        f.write('Scaling Image in Detection Phase: {}\n'.format(args.scaling_det))


    # Create Model
    class_weight = np.array([1, 1]).astype(np.float32)
    if args.gpu >= 0:
        class_weight = cuda.to_gpu(class_weight)

    print('Initializing models...')

    nsn = get_model(args)
    args.model = 'NDN'
    args.ch_base = 16
    ndn = get_model(args)
    if args.model_nsn is not None:
        print('Load NSN from', args.model_nsn)
        try:
            chainer.serializers.load_npz(args.model_nsn, nsn)
        except:
            chainer.serializers.load_hdf5(args.model_nsn, nsn)
    if args.model_ndn is not None:
        print('Load NDN from', args.model_ndn)
        try:
            chainer.serializers.load_npz(args.model_ndn, ndn)
        except:
            chainer.serializers.load_hdf5(args.model_ndn, ndn)
    if args.gpu >= 0:
        cuda.get_device(args.gpu).use()  # Make a specified GPU current
        nsn.to_gpu()  # Copy the SegmentNucleus model to the GPU
        ndn.to_gpu()

    # NSN_SGD
    # nsn = Model_L2(
    #     ndim=3,
    #     n_class=2,
    #     init_channel=16,
    #     kernel_size=3,
    #     pool_size=2,
    #     ap_factor=2,
    #     gpu=args.gpu,
    #     class_weight=class_weight,
    #     loss_func='F.softmax_dice_loss'
    # )
    #
    # # NDN_Adam
    # ndn = Model_L4(
    #     ndim=3,
    #     n_class=2,
    #     init_channel=12,
    #     kernel_size=5,
    #     pool_size=2,
    #     ap_factor=2,
    #     gpu=args.gpu,
    #     class_weight=class_weight,
    #     loss_func='F.softmax_cross_entropy'
    # )

    # Def-NDN_Adam
    # ndn = Model_L3(class_weight=class_weight, n_class=2, init_channel=8,
    #                kernel_size=3, pool_size=2, ap_factor=2, gpu=args.gpu)

    # Load Model

    chainer.serializers.load_npz(args.model_ndn, ndn)
    chainer.serializers.load_npz(args.model_nsn, nsn)
    #chainer.serializers.load_hdf5(args.model_nsn, nsn)
    #chainer.serializers.load_hdf5(args.model_ndn, ndn)

    if args.gpu >= 0:
        cuda.get_device(args.gpu).use()  # Make a specified GPU current
        nsn.to_gpu()  # Copy the SegmentNucleus model to the GPU
        ndn.to_gpu()

    dlist = os.listdir(args.indir)
    with open(opbase + psep + 'result.txt', 'a') as f:
        try:
            dlist.pop(dlist.index('.DS_Store'))
        except:
            pass
        dlist = np.sort(dlist)
        test_nsn = TestNSN(
            model=nsn,
            patchsize=args.patchsize_seg,
            stride=args.stride_seg,
            resolution=(args.resolution_x, args.resolution_y, args.resolution_z),
            scaling=args.scaling_seg,
            opbase=opbase,
            gpu=args.gpu,
            ndim=args.ndim
            )
        test_ndn = TestNDN(
            model=ndn,
            patchsize=args.patchsize_det,
            stride=args.stride_det,
            resolution=(args.resolution_x, args.resolution_y, args.resolution_z),
            scaling=args.scaling_det,
            delv=args.delete,
            opbase=opbase,
            gpu=args.gpu,
            ndim=args.ndim
            )
        for dl in dlist:
            image_path = args.indir + psep + dl
            print('[{}]'.format(image_path))
            f.write('[{}]\n'.format(image_path))

            ### Segmentation Phase ###
            seg_img = test_nsn.NuclearSegmentation(image_path)

            ### Detection Phase ###
            det_img = test_ndn.NuclearDetection(image_path)

            ### Post-Processing ###
            if det_img.sum() > 0:
                distance = ndimage.distance_transform_edt(seg_img)
                wsimage = watershed(-distance, det_img, mask=seg_img)
            else:
                wsimage = morphology.label(seg_img, neighbors=4)
            labels = np.unique(wsimage)
            wsimage = np.searchsorted(labels, wsimage)
            filename = opbase + psep + wsbase + psep + 'ws_{}.tif'.format(image_path[image_path.rfind('/')+1:image_path.rfind('.')])
            io.imsave(filename, wsimage.astype(np.uint16))

            f.write('Number of Nuclei: {}\n'.format(wsimage.max()))
            volumes = np.unique(wsimage, return_counts=True)[1][1:]
            f.write('Mean Volume of Nuclei: {}\n'.format(volumes.mean()))
            f.write('Volume of Nuclei: {}\n'.format(volumes))

    end_time = time.time()
    etime = end_time - start_time
    with open(opbase + psep + 'result.txt', 'a') as f:
        f.write('======================================\n')
        f.write('Elapsed time is (sec) {} \n'.format(etime))
    print('Elapsed time is (sec) {}'.format(etime))
    print('QCA Net Completed Process!')

if __name__ == '__main__':
    main()
