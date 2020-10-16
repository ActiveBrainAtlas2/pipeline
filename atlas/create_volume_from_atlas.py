import argparse
import os
import sys
import numpy as np
from timeit import default_timer as timer
import collections
from pymicro.view.vol_utils import compute_affine_transform
import cv2
from pprint import pprint
from superpose3d import Superpose3D
from _collections import OrderedDict
start = timer()
HOME = os.path.expanduser("~")
PATH = os.path.join(HOME, 'programming/pipeline_utility')
sys.path.append(PATH)
from utilities.sqlcontroller import SqlController
from utilities.file_location import FileLocationManager
from utilities.utilities_cvat_neuroglancer import get_structure_number, NumpyToNeuroglancer, get_segment_properties

def create_atlas(animal):

    fileLocationManager = FileLocationManager(animal)
    atlas_name = 'atlasV7'
    DATA_PATH = '/net/birdstore/Active_Atlas_Data/data_root'
    ROOT_DIR = '/net/birdstore/Active_Atlas_Data/data_root/pipeline_data'
    THUMBNAIL_DIR = os.path.join(ROOT_DIR, animal, 'preps', 'CH1', 'thumbnail')
    ATLAS_PATH = os.path.join(DATA_PATH, 'atlas_data', atlas_name)
    ORIGIN_PATH = os.path.join(ATLAS_PATH, 'origin')
    VOLUME_PATH = os.path.join(ATLAS_PATH, 'structure')
    OUTPUT_DIR = os.path.join(fileLocationManager.neuroglancer_data, 'atlas')
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    origin_files = sorted(os.listdir(ORIGIN_PATH))
    volume_files = sorted(os.listdir(VOLUME_PATH))
    sqlController = SqlController(animal)
    resolution = sqlController.scan_run.resolution
    # the atlas uses a 10um scale
    SCALE = (10 / resolution)

    structure_volume_origin = {}
    for volume_filename, origin_filename in zip(volume_files, origin_files):
        structure = os.path.splitext(volume_filename)[0]
        if structure not in origin_filename:
            print(structure, origin_filename)
            break

        color = get_structure_number(structure.replace('_L', '').replace('_R', ''))

        origin = np.loadtxt(os.path.join(ORIGIN_PATH, origin_filename))
        volume = np.load(os.path.join(VOLUME_PATH, volume_filename))

        volume = np.rot90(volume, axes=(0, 1))
        volume = np.flip(volume, axis=0)
        volume[volume > 0.8] = color
        volume = volume.astype(np.uint8)

        structure_volume_origin[structure] = (volume, origin)

    aligned_shape = np.array((sqlController.scan_run.width, sqlController.scan_run.height))
    z_length = len(os.listdir(THUMBNAIL_DIR))

    downsampled_aligned_shape = np.round(aligned_shape / SCALE).astype(int)

    x_length = downsampled_aligned_shape[1] + 0
    y_length = downsampled_aligned_shape[0] + 0

    atlasV7_volume = np.zeros((x_length, y_length, z_length), dtype=np.uint32)


    ##### actual data for both sets of points
    MD589_centers = {'5N_L': [23790, 13025, 160],
                     '5N_R': [20805, 14163, 298],
                     '7n_L': [20988, 18405, 177],
                     '7n_R': [24554, 13911, 284],
                     'DC_L': [24482, 11985, 134],
                     'DC_R': [20424, 11736, 330],
                     'LC_L': [25290, 11750, 180],
                     'LC_R': [24894, 12079, 268],
                     'SC': [24226, 6401, 220]}
    MD589_centers = OrderedDict(MD589_centers)
    MD589_list = []
    for value in MD589_centers.values():
        MD589_list.append((value[1] / SCALE, value[0] / SCALE, value[2]))
    MD589 = np.array(MD589_list)

    atlas_centers = {'5N_L': [460.53, 685.58, 155],
                     '5N_R': [460.53, 685.58, 293],
                     '7n_L': [499.04, 729.94, 172],
                     '7n_R': [499.04, 729.94, 276],
                     'DC_L': [580.29, 650.66, 130],
                     'DC_R': [580.29, 650.66, 318],
                     'LC_L': [505.55, 629.99, 182],
                     'LC_R': [505.55, 629.99, 266],
                     'SC': [376.87, 453.2, 226],
                     }
    atlas_centers = OrderedDict(atlas_centers)
    ATLAS = np.array(list(atlas_centers.values()), dtype=np.float32)

    md589_centroid = np.mean(MD589, axis=0)
    atlas_centroid = np.mean(ATLAS, axis=0)
    print('volume centriods', md589_centroid, atlas_centroid)

    # 2. basic least squares
    n = MD589.shape[0]
    pad = lambda x: np.hstack([x, np.ones((x.shape[0], 1))])
    unpad = lambda x: x[:, :-1]
    Xp = pad(MD589)
    Yp = pad(ATLAS)
    # Solve the least squares problem X * A = Y
    # to find our transformation matrix A
    A, residuals, rank, s = np.linalg.lstsq(Xp, Yp, rcond=None)
    transform = lambda x: unpad(np.dot(pad(x), A))
    #A[np.abs(A) < 1e-10] = 0
    #print(A)


    atlas_minmax = []
    trans_minmax = []
    for structure, (volume, origin) in sorted(structure_volume_origin.items()):
        x, y, z = origin
        x_start = int(x) + x_length // 2
        y_start = int(y) + y_length // 2
        z_start = int(z) // 2 + z_length // 2
        atlas_minmax.append((x_start, y_start))
        print(str(structure).ljust(8), 'original x', x_start, 'y', y_start, 'z', z_start, end="\t")

        original_array = np.array([x_start, y_start, z_start])
        original_array = np.vstack((original_array, [1,1,1]))
        results  = transform(original_array)[0:1]
        xf2 = results[0,0]
        yf2 = results[0,1]
        zf2 = results[0,2]
        print('least squares:', round(xf2), 'y', round(yf2), 'z', round(zf2), end="\n")
        trans_minmax.append((xf2,yf2))


        x_start = int(round(xf2))
        y_start = int(round(yf2))
        z_start = int(round(zf2))

        x_end = x_start + volume.shape[0]
        y_end = y_start + volume.shape[1]
        z_end = z_start + (volume.shape[2] + 1) // 2

        z_indices = [z for z in range(volume.shape[2]) if z % 2 == 0]
        volume = volume[:, :, z_indices]
        try:
            atlasV7_volume[x_start:x_end, y_start:y_end, z_start:z_end] += volume
        except:
            print('could not add', structure, x_start,y_start, z_start)

    # check range of x and y
    print('min,max x for atlas', np.min([x[0] for x in atlas_minmax]),np.max([x[0] for x in atlas_minmax]))
    print('min,max y for atlas', np.min([x[1] for x in atlas_minmax]),np.max([x[1] for x in atlas_minmax]))

    print('min,max x for trans', np.min([x[0] for x in trans_minmax]),np.max([x[0] for x in trans_minmax]))
    print('min,max y for trans', np.min([x[1] for x in trans_minmax]),np.max([x[1] for x in trans_minmax]))

    resolution = int(resolution * 1000 * SCALE)
    #resolution = 0.46 * 1000 * SCALE
    #resolution = 10000
    print('Resolution',resolution)
    if False:
        #def __init__(self, volume, scales, offset=[0, 0, 0], layer_type='segmentation'):

        ng = NumpyToNeuroglancer(atlasV7_volume, [resolution, resolution, 20000], offset=[0,0,0])
        ng.init_precomputed(OUTPUT_DIR)
        ng.add_segment_properties(get_segment_properties())
        ng.add_downsampled_volumes()
        ng.add_segmentation_mesh()


    end = timer()
    print(f'Finito! Program took {end - start} seconds')

    #outpath = os.path.join(ATLAS_PATH, f'{atlas_name}.npy')
    #with open(outpath, 'wb') as file:
    #    np.save(file, atlasV7_volume)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work on Animal')
    parser.add_argument('--animal', help='Enter the animal', required=True)
    args = parser.parse_args()
    animal = args.animal
    create_atlas(animal)

