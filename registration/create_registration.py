"""
Note, file must be sequentially named from 000.tif  -> 468.tif
 where 468 is the last tif and there are a total of 469 files
"""
import argparse
import pickle
from tqdm import tqdm
import os, sys
import numpy as np
from collections import OrderedDict
from shutil import move
import subprocess
import SimpleITK as sitk

sys.path.append(os.path.join(os.getcwd(), '../'))

from utilities.sqlcontroller import SqlController
from utilities.utilities_registration import create_warp_transforms, register_correlation
from utilities.alignment_utility import SCALING_FACTOR
from utilities.file_location import FileLocationManager


def create_register(animal, iterations):

    fileLocationManager = FileLocationManager(animal)
    sqlController = SqlController(animal)

    # define variables
    INPUT = os.path.join(fileLocationManager.prep, 'CH1', 'thumbnail_cleaned')
    ALIGNED = os.path.join(fileLocationManager.prep, 'CH1', 'thumbnail_aligned')
    resolution = 'thumbnail'
    width = sqlController.scan_run.width
    height = sqlController.scan_run.height
    max_width = int(width * SCALING_FACTOR)
    max_height = int(height * SCALING_FACTOR)
    bgcolor = 'black'  # this should be black, but white lets you see the rotation and shift
    rotations = OrderedDict()
    transforms = OrderedDict()
    #####header
    print('Iteration'.rjust(10), end=" ")
    print('Total R'.rjust(15), end=" ")
    print('Total X'.rjust(15), end=" ")
    print('Total Y'.rjust(15), end=" ")
    print('Max R'.rjust(10), end=" ")
    print('Max X'.rjust(10), end=" ")
    print('Max Y'.rjust(10))

    for repeats in range(0, iterations):
        transformation_to_previous_section = OrderedDict()
        rot_rads = []
        xshifts = []
        yshifts = []

        files = sorted(os.listdir(INPUT))
        files = files[0:5]

        for i in range(1, len(files)):
            fixed_index = str(i - 1).zfill(3)
            moving_index = str(i).zfill(3)

            R,t, rot_rad, xshift, yshift, transform = register_correlation(INPUT, fixed_index, moving_index)
            T = np.vstack([np.column_stack([R, t]), [0, 0, 1]])
            transformation_to_previous_section[files[i]] = T
            rot_rads.append(np.abs(rot_rad))
            xshifts.append(np.abs(xshift))
            yshifts.append(np.abs(yshift))

            if repeats == 0:
                rotations[files[i]] = T
                composite_transform = sitk.CompositeTransform([transform])
            else:
                ##### CHECK, is this correct? I'm multiplying the rotation matrix with itself
                ##### each iteration
                composite_transform.AddTransform(transform)
                rotations[files[i]] = rotations[files[i]] @ T

            transforms[files[i]] = composite_transform


        ##### This block of code is from Yuncong so I didn't write it.
        anchor_index = len(files) // 2 # middle section of the brain
        transformation_to_anchor_section = {}
        # Converts every transformation
        for moving_index in range(len(files)):
            if moving_index == anchor_index:
                transformation_to_anchor_section[files[moving_index]] = np.eye(3)
            elif moving_index < anchor_index:
                T_composed = np.eye(3)
                for i in range(anchor_index, moving_index, -1):
                    T_composed = np.dot(np.linalg.inv(transformation_to_previous_section[files[i]]), T_composed)
                transformation_to_anchor_section[files[moving_index]] = T_composed
            else:
                T_composed = np.eye(3)
                for i in range(anchor_index + 1, moving_index + 1):
                    T_composed = np.dot(transformation_to_previous_section[files[i]], T_composed)
                transformation_to_anchor_section[files[moving_index]] = T_composed

        # scale the translations to either the thumbnail or the full resolution sized images
        warp_transforms = create_warp_transforms(animal, transformation_to_anchor_section, 'thumbnail', resolution)
        ordered_transforms = OrderedDict(sorted(warp_transforms.items()))
        for file, arr in ordered_transforms.items():
            T = np.linalg.inv(arr)
            sx = T[0, 0]
            sy = T[1, 1]
            rx = T[1, 0]
            ry = T[0, 1]
            tx = T[0, 2]
            ty = T[1, 2]
            # sx, rx, ry, sy, tx, ty
            op_str = f" +distort AffineProjection '{sx},{rx},{ry},{sy},{tx},{ty}'"
            op_str += f' -crop {max_width}x{max_height}+0.0+0.0!'
            input_fp = os.path.join(INPUT, file)
            output_fp = os.path.join(ALIGNED, file)
            if os.path.exists(output_fp):
                continue

            cmd = f"convert {input_fp} -define white-point=0x0 +repage -virtual-pixel background -background {bgcolor} {op_str} -flatten -compress lzw {output_fp}"
            subprocess.run(cmd, shell=True)

        ##### eachloop
        tot_rot = round(sum(rot_rads),5)
        tot_xsh = round(sum(xshifts),5)
        tot_ysh = round(sum(yshifts),5)
        max_rot = round(max(rot_rads),5)
        max_xsh = round(max(xshifts),5)
        max_ysh = round(max(yshifts),5)


        print(str(repeats+1).rjust(10), end=" ")
        print('{:07.5f}'.rjust(15).format(tot_rot), end=" ")
        print('{:07.5f}'.rjust(15).format(tot_xsh), end=" ")
        print('{:07.5f}'.rjust(15).format(tot_ysh), end=" ")
        print('{:07.5f}'.rjust(10).format(max_rot), end=" ")
        print('{:07.5f}'.rjust(10).format(max_xsh), end=" ")
        print('{:07.5f}'.rjust(10).format(max_ysh))

        ## move aligned images to cleaned and repeat loop
        if repeats < iterations - 1:
            for file in os.listdir(INPUT):
                filepath = os.path.join(INPUT, file)
                os.unlink(filepath)
            for file in files:
                move(os.path.join(ALIGNED, file), INPUT)

    # Store data (serialize)
    rotation_storage = os.path.join(fileLocationManager.elastix_dir, 'rotations.pickle')
    with open(rotation_storage, 'wb') as handle:
        pickle.dump(rotations, handle)

    #print(transforms)









if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work on Animal')
    parser.add_argument('--animal', help='Enter the animal', required=True)
    parser.add_argument('--iterations', help='Enter iteration count', required=False, default=4)

    args = parser.parse_args()
    animal = args.animal
    iterations = int(args.iterations)

    create_register(animal, iterations)



