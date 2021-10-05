"""
This gets the CSV data of the 3 foundation brains' annotations.
These annotations were done by Lauren, Beth, Yuncong and Harvey
(i'm not positive about this)
The annotations are full scale vertices.

This code takes the contours and does the following:
1. create 3d volumn from the contours
2. find the center of mass
3. saving COMs in the database, saving COM and volumns in the file system
"""
import argparse
import json
import os
import sys
import cv2
import numpy as np
from tqdm import tqdm
from scipy.ndimage.measurements import center_of_mass
HOME = os.path.expanduser("~")
PATH = os.path.join(HOME, 'programming/pipeline_utility/src')
sys.path.append(PATH)
from lib.file_location import DATA_PATH
from lib.utilities_atlas import ATLAS
from lib.sqlcontroller import SqlController

DOWNSAMPLE_FACTOR = 32

class VolumnMaker:
    def __init__(self,animal,debug):
        self.animal = animal
        self.debug = debug
        self.sqlController = SqlController(self.animal)

    def save_volume_and_COMs(self,atlas_name, structure, volume, xyz_offsets):
        x, y, z = xyz_offsets
        volume = np.swapaxes(volume, 0, 2)
        volume = np.rot90(volume, axes=(0,1))
        volume = np.flip(volume, axis=0)
        OUTPUT_DIR = os.path.join(DATA_PATH, 'atlas_data', atlas_name, self.animal)
        volume_filepath = os.path.join(OUTPUT_DIR, 'structure', f'{structure}.npy')
        os.makedirs(os.path.join(OUTPUT_DIR, 'structure'), exist_ok=True)
        np.save(volume_filepath, volume)
        com_filepath = os.path.join(OUTPUT_DIR, 'origin', f'{structure}.txt')
        os.makedirs(os.path.join(OUTPUT_DIR, 'origin'), exist_ok=True)
        np.savetxt(com_filepath, (x,y,z))
    
    def load_contour(self):
        CSVPATH = os.path.join(DATA_PATH, 'atlas_data', ATLAS, self.animal)
        jsonpath = os.path.join(CSVPATH,  'aligned_padded_structures.json')
        with open(jsonpath) as f:
            self.contours_per_structure = json.load(f)
        self.structures = list(self.contours_per_structure.keys())        

    def get_COM_and_volume(self,structurei):
        section_mins = []
        section_maxs = []
        for _, contour_points in structurei.items():
            contour_points = np.array(contour_points)
            section_mins.append(np.min(contour_points, axis=0))
            section_maxs.append(np.max(contour_points, axis=0))
        min_z = min([int(i) for i in structurei.keys()])
        min_x,min_y = np.min(section_mins, axis=0)
        max_x,max_y = np.max(section_maxs, axis=0)
        xspan = max_x - min_x
        yspan = max_y - min_y
        PADDED_SIZE = (int(yspan), int(xspan))
        volume = []
        for _, contour_points in sorted(structurei.items()):
            vertices = np.array(contour_points) - np.array((min_x, min_y))
            contour_points = (vertices).astype(np.int32)
            volume_slice = np.zeros(PADDED_SIZE, dtype=np.uint8)
            volume_slice = cv2.polylines(volume_slice, [contour_points], isClosed=True, color=1, thickness=1)
            volume_slice = cv2.fillPoly(volume_slice, pts=[contour_points], color=1)
            volume.append(volume_slice)
        volume = np.array(volume).astype(np.bool8)
        to_um = 32 * 0.452
        com = center_of_mass(volume)
        comx = (com[0] + min_x) * to_um
        comy = (com[1] + min_y) * to_um
        comz = (com[2] + min_z) * 20
        return (comx,comy,comz),volume
    
    def save_or_print_COM_and_volumn(self,com,structure,volume):
        comx, comy, comz = com
        if self.debug:
            print(animal, structure,'\tcom', '\tcom x y z', comx, comy, comz)
        else:
            self.sqlController.add_layer_data(abbreviation=structure, animal=animal, 
                                    layer='COM', x=comx, y=comy, section=comz, 
                                    person_id=2, input_type_id=1)
            # self.save_volume_and_COMs(ATLAS, structure, volume, (comx, comy, comz))

    def compute_and_save_COMs_and_volumes(self):
        self.load_contour()
        for structure in tqdm(self.structures):
            structurei = self.contours_per_structure[structure]
            com,volume = self.get_COM_and_volume(structurei)
            self.save_or_print_COM_and_volumn(com,structure,volume)
            


if __name__ == '__main__':
    # parser = argparse.ArgumentParser(description='Work on Animal')
    # parser.add_argument('--animal', help='Enter the animal', required=False)
    # parser.add_argument('--debug', help='Enter debug True|False', required=False,
    #                      default='true')
    # args = parser.parse_args()
    # animal = args.animal
    # debug = bool({'true': True, 'false': False}[str(args.debug).lower()])
    # if animal is None:
    #     animals = ['MD585', 'MD589', 'MD594']
    # else:
    #     animals = [animal]

    # for animal in animals:
    #     create_volumes(animal, debug)
    debug = False
    animals = ['MD585', 'MD589', 'MD594']
    for animal in animals:
        Volumnmaker = VolumnMaker(animal,debug)
        Volumnmaker.compute_and_save_COMs_and_volumes()