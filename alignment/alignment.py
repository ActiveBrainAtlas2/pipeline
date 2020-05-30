"""
This file does the following operations:
    1. fetches the files needed to process.
    2. runs the files in sequence through elastix
    3. parses the results from the elastix output file
    4. Sends those results to the Imagemagick convert program with the correct offsets and crop
"""
import os, sys
import argparse
import subprocess
from multiprocessing.pool import Pool
import numpy as np

sys.path.append(os.path.join(os.getcwd(), '../'))
from utilities.file_location import FileLocationManager
from utilities.alignment_utility import create_if_not_exists, load_consecutive_section_transform, convert_cropbox_fmt, \
    convert_resolution_string_to_um

ELASTIX_BIN = '/usr/bin/elastix'


def workershell(cmd):
    """
    Set up an shell command. That is what the shell true is for.
    Args:
        cmd:  a command line program with arguments in a string
    Returns: nothing
    """
    stderr_template = os.path.join(os.getcwd(), 'alignment.err.log')
    stdout_template = os.path.join(os.getcwd(), 'alignment.log')
    stdout_f = open(stdout_template, "w")
    stderr_f = open(stderr_template, "w")
    p = subprocess.Popen(cmd, shell=True, stderr=stderr_f, stdout=stdout_f)
    p.wait()


def run_elastix(stack, limit):
    """
    Sets up the arguments for running elastix in a sequence. Each file pair
    creates a sub directory with the results. Uses a pool to spawn multiple processes
    Args:
        stack: the animal
        limit:  how many jobs you want to run.
    Returns: nothing, just creates a lot of subdirs
    """
    fileLocationManager = FileLocationManager(stack)
    filepath = fileLocationManager.cleaned
    image_name_list = sorted(os.listdir(filepath))
    elastix_output_dir = fileLocationManager.elastix_dir
    param_file = "Parameters_Rigid_MutualInfo_noNumberOfSpatialSamples_4000Iters.txt"
    commands = []
    for i in range(1, len(image_name_list)):
        prev_img_name = os.path.splitext(image_name_list[i - 1])[0]
        curr_img_name = os.path.splitext(image_name_list[i])[0]
        prev_fp = os.path.join(filepath, image_name_list[i - 1])
        curr_fp = os.path.join(filepath, image_name_list[i])
        new_dir = '{}_to_{}'.format(curr_img_name, prev_img_name)
        output_subdir = os.path.join(elastix_output_dir, new_dir)

        if os.path.exists(output_subdir) and 'TransformParameters.0.txt' in os.listdir(output_subdir):
            # print('{} to {} already exists and so skipping.'.format(curr_img_name, prev_img_name))
            continue


        command = ['rm', '-rf', output_subdir]
        subprocess.run(command)
        create_if_not_exists(output_subdir)
        param_fp = os.path.join(os.getcwd(), param_file)
        #command = [ELASTIX_BIN, '-f', prev_fp, '-m', curr_fp, '-p', param_fp, '-out', output_subdir]
        command = '{} -f {} -m {} -p {} -out {}'.format(ELASTIX_BIN, prev_fp, curr_fp, param_fp, output_subdir)
        commands.append(command)

    with Pool(limit) as p:
        p.map(workershell, commands)


def parse_elastix(stack):
    """
    After the elastix job is done, this goes into each subdirectory and parses the Transformation.0.txt file
    Args:
        stack: the animal
    Returns: a dictionary of key=filename, value = coordinates
    """
    fileLocationManager = FileLocationManager(stack)
    filepath = fileLocationManager.cleaned
    image_name_list = sorted(os.listdir(filepath))
    midpoint = len(image_name_list) // 2
    anchor_idx = midpoint
    # anchor_idx = len(image_name_list) - 1
    transformation_to_previous_sec = {}

    for i in range(1, len(image_name_list)):
        fixed_fn = os.path.splitext(image_name_list[i - 1])[0]
        moving_fn = os.path.splitext(image_name_list[i])[0]
        transformation_to_previous_sec[i] = load_consecutive_section_transform(stack, moving_fn, fixed_fn)

    transformation_to_anchor_sec = {}
    # Converts every transformation
    for moving_idx in range(len(image_name_list)):
        if moving_idx == anchor_idx:
            transformation_to_anchor_sec[image_name_list[moving_idx]] = np.eye(3)
        elif moving_idx < anchor_idx:
            T_composed = np.eye(3)
            for i in range(anchor_idx, moving_idx, -1):
                T_composed = np.dot(np.linalg.inv(transformation_to_previous_sec[i]), T_composed)
            transformation_to_anchor_sec[image_name_list[moving_idx]] = T_composed
        else:
            T_composed = np.eye(3)
            for i in range(anchor_idx + 1, moving_idx + 1):
                T_composed = np.dot(transformation_to_previous_sec[i], T_composed)
            transformation_to_anchor_sec[image_name_list[moving_idx]] = T_composed


    return transformation_to_anchor_sec

def convert_2d_transform_forms(arr):
    return np.vstack([arr, [0,0,1]])

def create_warp_transforms(stack, transforms, transforms_resol, resol):
    #transforms_resol = op['resolution']
    transforms_scale_factor = convert_resolution_string_to_um(stack, resolution=transforms_resol) / convert_resolution_string_to_um(stack, resolution=resol)
    tf_mat_mult_factor = np.array([[1, 1, transforms_scale_factor], [1, 1, transforms_scale_factor]])
    transforms_to_anchor = {
        img_name:
            convert_2d_transform_forms(np.reshape(tf, (3, 3))[:2] * tf_mat_mult_factor) for
        img_name, tf in transforms.items()}

    return transforms_to_anchor


def run_offsets(stack, transforms, limit):
    """
    This gets the dictionary from the above method, and uses the coordinates
    to feed into the Imagemagick convert program. This method also uses a Pool to spawn multiple processes.
    Args:
        stack: the animal
        transforms: the dictionary of file, coordinates
        limit: number of jobs
    Returns: nothing
    """
    fileLocationManager = FileLocationManager(stack)
    inpath = fileLocationManager.cleaned
    outpath = fileLocationManager.aligned
    commands = []
    warp_transforms = create_warp_transforms(stack, transforms, 'thumbnail', 'thumbnail')
    for file, arr in warp_transforms.items():
        T = np.linalg.inv(arr)
        op_str = " +distort AffineProjection '%(sx)f,%(rx)f,%(ry)f,%(sy)f,%(tx)f,%(ty)f' " % {
            'sx': T[0, 0], 'sy': T[1, 1], 'rx': T[1, 0], 'ry': T[0, 1], 'tx': T[0, 2], 'ty': T[1, 2]}
        #print(file, op_str)

        #x, y, w, h = convert_cropbox_fmt(data=arr, out_fmt='arr_xywh', in_fmt='arr_xywh', stack=stack)
        x, y, w, h = 1,1,1,1
        op_strXXX = ' -crop %(w)sx%(h)s%(x)s%(y)s\! ' % {'x': '+' + str(x) if int(x) >= 0 else str(x),
                                                       'y': '+' + str(y) if int(y) >= 0 else str(y),
                                                       'w': str(w), 'h': str(h)}

        #op_str += ' -crop 2001.0x1001.0+0.0+0.0\!'
        op_str += ' -crop 1740.0x1040.0+0.0+0.0\!'

        input_fp = os.path.join(inpath, file)
        output_fp = os.path.join(outpath, file)
        cmd = "convert %(input_fp)s  +repage -virtual-pixel background -background %(bg_color)s %(op_str)s -flatten -compress lzw \"%(output_fp)s\"" % \
                {'op_str': op_str, 'input_fp': input_fp, 'output_fp': output_fp, 'bg_color': 'black'}
        commands.append(cmd)

    with Pool(limit) as p:
        p.map(workershell, commands)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work on Animal')
    parser.add_argument('--animal', help='Enter the animal animal', required=True)
    parser.add_argument('--njobs', help='How many processes to spawn', default=12)
    args = parser.parse_args()
    animal = args.animal
    njobs = int(args.njobs)
    run_elastix(animal, njobs)
    transforms = parse_elastix(animal)
    run_offsets(animal, transforms, njobs)
