"""
Important notes,
If your fixed image has a smaller field of view than your moving image, 
your moving image will be cropped. (This is what happens when the brain stem
gets cropped out. However, when the fixed image is bigger than the moving image, we get the following error:
Too many samples map outside moving image buffer. The moving image needs to be properly initialized.

In other words, only the part your moving image 
that overlap with the fixed image is included in your result image.
To warp the whole image, you can edit the size of the domain in the 
transform parameter map to match your moving image, and pass your moving image and 
the transform parameter map to sitk.Transformix().
10um allen is 1320x800
25um allen is 528x320
aligned volume @ 32 is 2047x1109 - unreg size matches allen10um
aligned volume @ 64 is 1024x555 - unreg size matches allen25um
aligned volume @ 128 is 512x278
aligned volume @50 is 1310x710
full aligned is 65500x35500
Need to scale a moving image as close as possible to the fixed image
COM info:
allen SC: (368, 62, 227)
pred  SC: 369, 64, 219
"""

import argparse
from collections import defaultdict
import os
import shutil
import sys
import numpy as np
from pathlib import Path
from skimage import io
from tqdm import tqdm
import SimpleITK as sitk
import itk
from taskqueue import LocalTaskQueue
import igneous.task_creation as tc
import pandas as pd
import cv2
from allensdk.core.mouse_connectivity_cache import MouseConnectivityCache
from tifffile import imwrite

PIPELINE_ROOT = Path('./src').absolute()
sys.path.append(PIPELINE_ROOT.as_posix())

from library.controller.polygon_sequence_controller import PolygonSequenceController
from library.controller.sql_controller import SqlController
from library.image_manipulation.neuroglancer_manager import NumpyToNeuroglancer
from library.image_manipulation.filelocation_manager import FileLocationManager
from library.utilities.utilities_mask import normalize16, normalize8
from library.utilities.utilities_process import read_image, write_image
from library.controller.annotation_session_controller import AnnotationSessionController

def compute_dice_coefficient(source_image: itk.Image, target_image: itk.Image) -> float:
    """Compute the dice coefficient to compare volume overlap between two label regions"""
    dice_filter = itk.LabelOverlapMeasuresImageFilter[type(source_image)].New()
    dice_filter.SetInput(source_image)
    dice_filter.SetTargetImage(target_image)
    dice_filter.Update()
    return dice_filter.GetDiceCoefficient()

def dice(im1, im2):
    """
    Computes the Dice coefficient, a measure of set similarity.
    Parameters
    ----------
    im1 : array-like, bool
        Any array of arbitrary size. If not boolean, will be converted.
    im2 : array-like, bool
        Any other array of identical size. If not boolean, will be converted.
    Returns
    -------
    dice : float
        Dice coefficient as a float on range [0,1].
        Maximum similarity = 1
        No similarity = 0
        
    Notes
    -----
    The order of inputs for `dice` is irrelevant. The result will be
    identical if `im1` and `im2` are switched.
    """
    im1 = np.asarray(im1).astype(bool)
    im2 = np.asarray(im2).astype(bool)

    if im1.shape != im2.shape:
        raise ValueError("Shape mismatch: im1 and im2 must have the same shape.")

    # Compute Dice coefficient
    intersection = np.logical_and(im1, im2)
    return 2. * intersection.sum() / (im1.sum() + im2.sum())

class VolumeRegistration:
    """This class takes a downsampled image stack and registers it to the Allen volume    
    """

    def __init__(self, animal, channel, um, atlas, orientation, debug):
        self.animal = animal
        self.debug = debug
        self.atlas = atlas
        self.um = um
        self.channel = f'CH{channel}'
        self.output_dir = f'{self.atlas}{um}um'
        self.scaling_factor = 64 # This is the downsampling factor used to create the aligned volume
        self.fileLocationManager = FileLocationManager(animal)
        self.thumbnail_aligned = os.path.join(self.fileLocationManager.prep, self.channel, 'thumbnail_aligned')
        self.moving_volume_path = os.path.join(self.fileLocationManager.prep, self.channel, 'moving_volume.tif')
        self.fixed_volume_path = os.path.join(self.fileLocationManager.registration_info, f'{atlas}_{um}um_{orientation}.tif')
        self.elastix_output = os.path.join(self.fileLocationManager.prep, 'elastix_output', self.output_dir)
        self.reverse_elastix_output = os.path.join(self.fileLocationManager.prep, 'reverse_elastix_output', self.output_dir)
        self.registered_output = os.path.join(self.fileLocationManager.prep, self.channel,  'registered', self.output_dir)
        self.registered_point_file = os.path.join(self.registered_output, 'outputpoints.txt')
        self.unregistered_pickle_file = os.path.join(self.fileLocationManager.prep, 'points.pkl')
        self.unregistered_text_file = os.path.join(self.fileLocationManager.prep, 'points.txt')
        self.unregistered_point_file = os.path.join(self.fileLocationManager.prep, 'points.pts')
        self.neuroglancer_data_path = os.path.join(self.fileLocationManager.neuroglancer_data, f'{self.channel}_{self.atlas}{um}um')
        self.number_of_sampling_attempts = "10"
        if self.debug:
            self.rigidIterations = "100"
            self.affineIterations = "100"
            self.bsplineIterations = "200"
        else:
            self.rigidIterations = "1000"
            self.affineIterations = "2500"
            self.bsplineIterations = "15000"

        if not os.path.exists(self.fixed_volume_path):
            print(f'{self.fixed_volume_path} does not exist, exiting.')
            sys.exit()        
 

    def register_volume(self):
        """This will perform the elastix registration of the volume to the atlas.
        It first does an affine registration, then a bspline registration.
        """
        
        os.makedirs(self.elastix_output, exist_ok=True)
        os.makedirs(self.registered_output, exist_ok=True)

        elastixImageFilter = self.setup_registration(self.fixed_volume_path, self.moving_volume_path, self.elastix_output)
        resultImage = elastixImageFilter.Execute()         
        # simg1 = sitk.Cast(sitk.RescaleIntensity(resultImage), sitk.sitkUInt16)
        sitk.WriteImage(resultImage, os.path.join(self.registered_output, 'result.tif'))


    def reverse_register_volume(self):
        """This method also uses an affine and a bspline registration process, but it does 
        it in reverse. The fixed and moving images get switched so we can get the transformation
        for the points to get registered to the atlas. 
        """

        os.makedirs(self.reverse_elastix_output, exist_ok=True)

        # switch moving and fixed
        elastixImageFilter = self.setup_registration(self.moving_volume_path, self.fixed_volume_path, self.reverse_elastix_output)
        elastixImageFilter.Execute()

    def setup_registration(self, imagepath1, imagepath2, outputpath):
        fixedImage = sitk.ReadImage(imagepath1)
        movingImage = sitk.ReadImage(imagepath2)

        elastixImageFilter = sitk.ElastixImageFilter()
        elastixImageFilter.SetFixedImage(fixedImage)
        elastixImageFilter.SetMovingImage(movingImage)

        # The translation is very important as it centers the two volumes
        translateParameterMap = sitk.GetDefaultParameterMap('translation')
        
        rigidParameterMap = sitk.GetDefaultParameterMap('rigid')        
        rigidParameterMap["MaximumNumberOfIterations"] = [self.rigidIterations] # 250 works ok
        
        rigidParameterMap["MaximumNumberOfSamplingAttempts"] = [self.number_of_sampling_attempts]
        rigidParameterMap["UseDirectionCosines"] = ["true"]
        rigidParameterMap["NumberOfResolutions"]= ["6"]
        rigidParameterMap["NumberOfSpatialSamples"] = ["4000"]
        rigidParameterMap["WriteResultImage"] = ["false"]

        
        affineParameterMap = sitk.GetDefaultParameterMap('affine')
        affineParameterMap["UseDirectionCosines"] = ["true"]
        affineParameterMap["MaximumNumberOfIterations"] = [self.affineIterations] # 250 works ok
        affineParameterMap["MaximumNumberOfSamplingAttempts"] = [self.number_of_sampling_attempts]
        affineParameterMap["NumberOfResolutions"]= ["6"]
        affineParameterMap["NumberOfSpatialSamples"] = ["4000"]
        affineParameterMap["WriteResultImage"] = ["false"]

        bsplineParameterMap = sitk.GetDefaultParameterMap('bspline')
        bsplineParameterMap["MaximumNumberOfIterations"] = [self.bsplineIterations] # 150 works ok
        bsplineParameterMap["WriteResultImage"] = ["true"]
        bsplineParameterMap["UseDirectionCosines"] = ["true"]
        bsplineParameterMap["FinalGridSpacingInVoxels"] = [f"{self.um}"]
        bsplineParameterMap["MaximumNumberOfSamplingAttempts"] = [self.number_of_sampling_attempts]
        bsplineParameterMap["NumberOfResolutions"]= ["6"]
        bsplineParameterMap["GridSpacingSchedule"] = ["6.219", "4.1", "2.8", "1.9", "1.4", "1.0"]
        bsplineParameterMap["NumberOfSpatialSamples"] = ["4000"]
        del bsplineParameterMap["FinalGridSpacingInPhysicalUnits"]

        elastixImageFilter.SetParameterMap(translateParameterMap)
        elastixImageFilter.AddParameterMap(rigidParameterMap)
        elastixImageFilter.AddParameterMap(affineParameterMap)
        elastixImageFilter.AddParameterMap(bsplineParameterMap)
        elastixImageFilter.SetOutputDirectory(outputpath)
        elastixImageFilter.LogToFileOn();
        elastixImageFilter.LogToConsoleOff()
        elastixImageFilter.SetLogFileName('elastix.log');
        if self.debug:
            elastixImageFilter.PrintParameterMap(translateParameterMap)    
            elastixImageFilter.PrintParameterMap(rigidParameterMap)    
            elastixImageFilter.PrintParameterMap(affineParameterMap)
            elastixImageFilter.PrintParameterMap(bsplineParameterMap)

        return elastixImageFilter

        

    def setup_transformix(self, outputpath):
        """Method used to transform volumes and points
        """
        
        os.makedirs(self.registered_output, exist_ok=True)

        transformixImageFilter = sitk.TransformixImageFilter()
        parameterMap0 = sitk.ReadParameterFile(os.path.join(outputpath, 'TransformParameters.0.txt'))
        parameterMap1 = sitk.ReadParameterFile(os.path.join(outputpath, 'TransformParameters.1.txt'))
        parameterMap2 = sitk.ReadParameterFile(os.path.join(outputpath, 'TransformParameters.2.txt'))
        parameterMap3 = sitk.ReadParameterFile(os.path.join(outputpath, 'TransformParameters.3.txt'))
        transformixImageFilter.SetTransformParameterMap(parameterMap0)
        transformixImageFilter.AddTransformParameterMap(parameterMap1)
        transformixImageFilter.AddTransformParameterMap(parameterMap2)
        transformixImageFilter.AddTransformParameterMap(parameterMap3)
        transformixImageFilter.LogToFileOn()
        transformixImageFilter.LogToConsoleOff()
        transformixImageFilter.SetOutputDirectory(self.registered_output)
        movingImage = sitk.ReadImage(self.moving_volume_path)
        transformixImageFilter.SetMovingImage(movingImage)
        return transformixImageFilter

    def transformix_volume(self):
        """Helper method when you want to rerun the same transform on another volume
        """
        
        transformixImageFilter = self.setup_transformix(self.elastix_output)
        transformixImageFilter.Execute()
        transformed = transformixImageFilter.GetResultImage()
        sitk.WriteImage(transformed, os.path.join(self.registered_output, 'result.tif'))

    def transformix_com(self):
        """Helper method when you want to rerun the transform on a set of points.
        Get the pickle file and transform it. It is in full resolution pixel size.
        The points in the pickle file need to be translated from full res pixel to
        the current resolution of the downsampled volume.
        Points are inserted in the DB in micrometers from the full resolution images

        
        The points.pts file takes THIS format:
        point
        3
        102.8 -33.4 57.0
        178.1 -10.9 14.5
        180.4 -18.1 78.9
        """
        d = pd.read_pickle(self.unregistered_pickle_file)
        point_dict = dict(sorted(d.items()))
        with open(self.unregistered_point_file, 'w') as f:
            f.write('point\n')
            f.write(f'{len(point_dict)}\n')
            for _, points in point_dict.items():
                x = points[0]/self.scaling_factor
                y = points[1]/self.scaling_factor
                z = points[2] # the z is not scaled
                #print(structure, points, x,y,z)
                f.write(f'{x} {y} {z}')
                f.write('\n')
        
        transformixImageFilter = self.setup_transformix(self.reverse_elastix_output)
        transformixImageFilter.SetFixedPointSetFileName(self.unregistered_point_file)
        transformixImageFilter.Execute()


    def transformix_polygons(self):
        """Helper method when you want to rerun the transform on a set of points.
        Get the pickle file and transform it. It is in full resolution pixel size.
        The points in the pickle file need to be translated from full res pixel to
        the current resolution of the downsampled volume.
        Points are inserted in the DB in micrometers from the full resolution images

        
        The points.pts file takes THIS format:
        point
        3
        102.8 -33.4 57.0
        178.1 -10.9 14.5
        180.4 -18.1 78.9
        """
        
        transformixImageFilter = self.setup_transformix(self.reverse_elastix_output)
        transformixImageFilter.SetFixedPointSetFileName(self.unregistered_point_file)
        transformixImageFilter.Execute()

    def create_itk(self):
        os.makedirs(self.registered_output, exist_ok=True)
        fixed_image = itk.imread(self.fixed_volume_path, itk.F)
        moving_image = itk.imread(self.moving_volume_path, itk.F)
        
        # init transform start
        # Translate to roughly position sample data on top of CCF data
        init_transform = itk.VersorRigid3DTransform[itk.D].New()  # Represents 3D rigid transformation with unit quaternion
        init_transform.SetIdentity()
        transform_initializer = itk.CenteredVersorTransformInitializer[
            type(fixed_image), type(moving_image)
        ].New()
        transform_initializer.SetFixedImage(fixed_image)
        transform_initializer.SetMovingImage(moving_image)
        transform_initializer.SetTransform(init_transform)
        transform_initializer.GeometryOn()  # We compute translation between the center of each image
        transform_initializer.ComputeRotationOff()  # We have previously verified that spatial orientation aligns
        transform_initializer.InitializeTransform()
        # initializer maps from the fixed image to the moving image,
        # whereas we want to map from the moving image to the fixed image.
        init_transform = init_transform.GetInverseTransform()
        print(init_transform)
        # init transform end
        # Apply translation without resampling the image by updating the image origin directly
        change_information_filter = itk.ChangeInformationImageFilter[type(moving_image)].New()
        change_information_filter.SetInput(moving_image)
        change_information_filter.SetOutputOrigin(
            init_transform.TransformPoint(itk.origin(moving_image))
        )
        change_information_filter.ChangeOriginOn()
        change_information_filter.UpdateOutputInformation()
        source_image_init = change_information_filter.GetOutput()
        # end apply translation
        
        parameter_object = itk.ParameterObject.New()
        rigid_parameter_map = parameter_object.GetDefaultParameterMap('rigid')
        affine_parameter_map = parameter_object.GetDefaultParameterMap('affine')
        bspline_parameter_map = parameter_object.GetDefaultParameterMap("bspline")
        bspline_parameter_map["FinalGridSpacingInVoxels"] = (f"{self.um}",)
        parameter_object.AddParameterMap(rigid_parameter_map)
        parameter_object.AddParameterMap(affine_parameter_map)
        parameter_object.AddParameterMap(bspline_parameter_map)
        parameter_object.RemoveParameter("FinalGridSpacingInPhysicalUnits")
        parameter_object.SetParameter("DefaultPixelValue", "0")
        parameter_object.SetParameter("NumberOfIterations", "1000")
        parameter_object.SetParameter("ResultImagePixelType", "float")
        registration_method = itk.ElastixRegistrationMethod[type(fixed_image), type(moving_image)
        ].New(
            fixed_image=fixed_image,
            moving_image=source_image_init,
            parameter_object=parameter_object,
            log_to_console=False,
        )
        registration_method.Update()
        resultImage = registration_method.GetOutput()
        itk.imwrite(resultImage, os.path.join(self.registered_output, 'result.tif'), compression=True) 
        ## write transformation DOES NOT WORK!
        #init_transformpath = os.path.join(self.registered_output, 'init-transform.tfm')
        #itk.transformwrite([init_transform], init_transformpath)
            
        for index in range(parameter_object.GetNumberOfParameterMaps()):
            registration_method.GetTransformParameterObject().WriteParameterFile(
            registration_method.GetTransformParameterObject().GetParameterMap(index),
            f"{self.registered_output}/elastix-transform.{index}.txt",)
        input_points = itk.PointSet[itk.F, 3].New()

        sqlController = SqlController(animal)
        
        polygon = PolygonSequenceController(animal=animal)        
        scale_xy = sqlController.scan_run.resolution
        z_scale = sqlController.scan_run.zresolution
        df_L = polygon.get_volume(self.animal, 3, 12)
        df_R = polygon.get_volume(self.animal, 3, 13)
        frames = [df_L, df_R]
        df = pd.concat(frames)
        len_L = df_L.shape[0]
        len_R = df_R.shape[0]
        len_total = df.shape[0]
        assert len_L + len_R == len_total, "Lengths of dataframes do not add up."

        for idx, (_, row) in enumerate(df.iterrows()):
            x = row['coordinate'][0]/scale_xy/self.scaling_factor
            y = row['coordinate'][1]/scale_xy/self.scaling_factor
            z = row['coordinate'][2]/z_scale
            point = [x,y,z]
            #xy = (x/scale_xy/self.scaling_factor, y/scale_xy/self.scaling_factor)
            #section = int(np.round(z/z_scale))
            #polygons[section].append(xy)
            input_points.GetPoints().InsertElement(idx, point)

        
        init_points = itk.PointSet[itk.F, 3].New()
        for idx in range(input_points.GetNumberOfPoints()):
            point = input_points.GetPoint(idx)
            init_points.GetPoints().InsertElement(
                idx, init_transform.TransformPoint(point)
            )
            print(f"{point} -> {init_points.GetPoint(idx)}")
        
        TRANSFORMIX_POINTSET_FILE = os.path.join(self.registered_output,"transformix_input_points.txt")        
        with open(TRANSFORMIX_POINTSET_FILE, "w") as f:
            f.write("point\n")
            f.write(f"{df.shape[0]}\n")
            for idx in range(input_points.GetNumberOfPoints()):
                point = input_points.GetPoint(idx)
                f.write(f"{point[0]} {point[1]} {point[2]}\n")

        N_ELASTIX_STAGES = 3

        toplevel_param = itk.ParameterObject.New()
        param = itk.ParameterObject.New()
        ELASTIX_TRANSFORM_FILENAMES = [os.path.join(self.registered_output, f"elastix-transform.{index}.txt")
            for index in range(N_ELASTIX_STAGES)]

        for elastix_transform_filename in ELASTIX_TRANSFORM_FILENAMES:
            param.ReadParameterFile(elastix_transform_filename)
            toplevel_param.AddParameterMap(param.GetParameterMap(0))        

        # Load reference image (required for transformix)
        average_template = itk.imread(self.fixed_volume_path, pixel_type=itk.F)
        # Procedural interface of transformix filter
        result_point_set = itk.transformix_pointset(
            average_template,
            toplevel_param,
            fixed_point_set_file_name=TRANSFORMIX_POINTSET_FILE,
            output_directory=self.registered_output)
        # Transformix will write results to self.registered_output/outputpoints.txt
        print("\n".join(
        [
            f"{output_point[11:18]} ---> {output_point[27:35]}"
            for output_point in result_point_set
        ]))

    def evaluate_registrationXXXX(self):
        TARGET_LABEL_IMAGE_FILEPATH = '/net/birdstore/Active_Atlas_Data/data_root/brains_info/registration/allen_25um_annnotations.tif'
        INPUT_LABEL_IMAGE_FILEPATH = os.path.join(self.registered_output, 'result.tif')
        TARGET_LABEL_VALUE = 4
        target_label_image = itk.imread(TARGET_LABEL_IMAGE_FILEPATH)
        target_label_image_f = itk.cast_image_filter(target_label_image, ttype=[type(target_label_image), itk.Image[itk.F,3]])
        target_binary_image = itk.binary_threshold_image_filter(
            target_label_image_f,
            lower_threshold=1,
            upper_threshold=8115,
            inside_value=1,
            outside_value=0,
            ttype=[type(target_label_image_f), itk.Image[itk.UC,target_label_image_f.GetImageDimension()]]
        )

        print(f'Binary labels: {np.unique(target_binary_image)}')
        
        transformed_source_label_image = itk.imread(INPUT_LABEL_IMAGE_FILEPATH, itk.UC)
        print(f'type of target fixed {type(target_binary_image)}')
        print(f'type of source moving {type(transformed_source_label_image)}')
        
        dice_score = compute_dice_coefficient(transformed_source_label_image, target_binary_image)
        print(f'Evaluated dice value: {dice_score}')

    def evaluate_registration(self):
        mcc = MouseConnectivityCache(resolution=25)
        rsp = mcc.get_reference_space()
        structure_id = 661
        structure_mask = rsp.make_structure_mask([structure_id], direct_only=False)
        structure_mask = np.swapaxes(structure_mask, 0, 2)
        ids, counts = np.unique(structure_mask, return_counts=True)
        print('structure mask, ids counts')
        print(ids)
        print(counts)
        

        print(f'mask dtype={structure_mask.dtype} shape={structure_mask.shape}')
        resultpath = os.path.join(self.registered_output, 'result.tif')
        #annotation = io.imread(annotationpath)

        resultImage = io.imread(resultpath)
        resultImage = normalize8(resultImage)
        resultImage[resultImage == 111] = 1
        resultImage[resultImage != 1] = 0
        resultImage = (resultImage == True)
        #resultImage = (resultImage * 254).astype(np.uint8)
        outpath = '/net/birdstore/Active_Atlas_Data/data_root/brains_info/registration/facialmask.tif'
        #imwrite(outpath, resultImage)
        print(f'resultImage dtype={resultImage.dtype} shape={resultImage.shape}')
        ids, counts = np.unique(resultImage, return_counts=True)
        print('result image, ids counts')
        print(ids)
        print(counts)

        dice_coefficient = dice(structure_mask, resultImage)
        
        print(f'Dice={dice_coefficient}')


        
    def transformix_pointsYYY(self):
        """Helper method when you want to rerun the transform on a set of points.
        Get the pickle file and transform it. It is in full resolution pixel size.
        The points in the pickle file need to be translated from full res pixel to
        the current resolution of the downsampled volume.
        Points are inserted in the DB in micrometers from the full resolution images

        
        The points.pts file takes THIS format:
        point
        3
        102.8 -33.4 57.0
        178.1 -10.9 14.5
        180.4 -18.1 78.9
        """
        # initialize init_transform
        fixed_image = itk.imread(self.fixed_volume_path, itk.F)
        moving_image = itk.imread(self.moving_volume_path, itk.F)
        # init transform start
        # Translate to roughly position sample data on top of CCF data
        init_transform = itk.VersorRigid3DTransform[itk.D].New()  # Represents 3D rigid transformation with unit quaternion
        init_transform.SetIdentity()
        transform_initializer = itk.CenteredVersorTransformInitializer[
            type(fixed_image), type(moving_image)
        ].New()
        transform_initializer.SetFixedImage(fixed_image)
        transform_initializer.SetMovingImage(moving_image)
        transform_initializer.SetTransform(init_transform)
        transform_initializer.GeometryOn()  # We compute translation between the center of each image
        transform_initializer.ComputeRotationOff()  # We have previously verified that spatial orientation aligns
        transform_initializer.InitializeTransform()
        # initializer maps from the fixed image to the moving image,
        # whereas we want to map from the moving image to the fixed image.
        init_transform = init_transform.GetInverseTransform()
        print(init_transform)
        
        input_points = itk.PointSet[itk.F, 3].New()

        sqlController = SqlController(animal)
        
        """
        polygon = PolygonSequenceController(animal=animal)        
        scale_xy = sqlController.scan_run.resolution
        z_scale = sqlController.scan_run.zresolution
        polygons = defaultdict(list)
        color = 0 # set it below the threshold set in mask class
        df_L = polygon.get_volume(self.animal, 3, 12)
        df_R = polygon.get_volume(self.animal, 3, 13)
        frames = [df_L, df_R]
        df = pd.concat(frames)
        len_L = df_L.shape[0]
        len_R = df_R.shape[0]
        len_total = df.shape[0]
        assert len_L + len_R == len_total, "Lengths of dataframes do not add up."

        for idx, (_, row) in enumerate(df.iterrows()):
            x = row['coordinate'][0]/scale_xy/self.scaling_factor
            y = row['coordinate'][1]/scale_xy/self.scaling_factor
            z = row['coordinate'][2]/z_scale
            point = [x,y,z]
            #xy = (x/scale_xy/self.scaling_factor, y/scale_xy/self.scaling_factor)
            #section = int(np.round(z/z_scale))
            #polygons[section].append(xy)
            input_points.GetPoints().InsertElement(idx, point)
        """
        idx = 0
        #x = 12236.70/25
        #y = 8549.40/25
        #z = 3040/25
        #point = [x,y,z]
        # good values
        x = 425 # -> 437
        y = 292 # -> 263
        z = 151 # 159

        point = [x,y,z]
        print(point)
        input_points.GetPoints().InsertElement(idx, point)
        
        init_points = itk.PointSet[itk.F, 3].New()
        for idx in range(input_points.GetNumberOfPoints()):
            point = input_points.GetPoint(idx)
            init_points.GetPoints().InsertElement(
                idx, init_transform.TransformPoint(point)
            )
            print(f"{point} -> {init_points.GetPoint(idx)}")
        
        TRANSFORMIX_POINTSET_FILE = os.path.join(self.registered_output,"transformix_input_points.txt")        
        with open(TRANSFORMIX_POINTSET_FILE, "w") as f:
            f.write("point\n")
            f.write(f"{init_points.GetNumberOfPoints()}\n")

            for idx in range(init_points.GetNumberOfPoints()):
                point = init_points.GetPoint(idx)
                f.write(f"{point[0]} {point[1]} {point[2]}\n")

        N_ELASTIX_STAGES = 3

        toplevel_param = itk.ParameterObject.New()
        param = itk.ParameterObject.New()
        ELASTIX_TRANSFORM_FILENAMES = [os.path.join(self.registered_output, f"elastix-transform.{index}.txt")
            for index in range(N_ELASTIX_STAGES)]

        for elastix_transform_filename in ELASTIX_TRANSFORM_FILENAMES:
            param.ReadParameterFile(elastix_transform_filename)
            toplevel_param.AddParameterMap(param.GetParameterMap(0))        

        # Load reference image (required for transformix)
        average_template = itk.imread(self.fixed_volume_path, pixel_type=itk.F)
        # Procedural interface of transformix filter
        result_point_set = itk.transformix_pointset(
            average_template,
            toplevel_param,
            fixed_point_set_file_name=TRANSFORMIX_POINTSET_FILE,
            output_directory=self.registered_output)
        # Transformix will write results to self.registered_output/outputpoints.txt
        print("\n".join(
        [
            f"{output_point[11:18]} ---> {output_point[27:35]}"
            for output_point in result_point_set
        ]))

        
    def transformix_points(self):
        fixed_image = itk.imread(self.fixed_volume_path, itk.F)
        moving_image = itk.imread(self.moving_volume_path, itk.F)
        # Import Default Parameter Map
        parameter_object = itk.ParameterObject.New()
        parameter_map_rigid = parameter_object.GetDefaultParameterMap('rigid')
        parameter_object.AddParameterMap(parameter_map_rigid)
        parameter_map_affine= parameter_object.GetDefaultParameterMap('affine')
        parameter_object.AddParameterMap(parameter_map_affine)
        parameter_map_bspline = parameter_object.GetDefaultParameterMap('bspline')
        parameter_object.AddParameterMap(parameter_map_bspline)
        # Call registration function
        result_image, result_transform_parameters = itk.elastix_registration_method(
            fixed_image, moving_image,
            parameter_object=parameter_object,
            log_to_console=True) 
        itk.imwrite(result_image, os.path.join(self.registered_output, 'result.tif'), compression=True) 
       
        idx = 0

        #x = 12236.70/25
        #y = 8549.40/25
        #z = 3040/25
        #point = [x,y,z]
        # good values
        x = 429 # -> 437
        y = 294 # -> 263
        z = 152
        # got 410 320 147
        # should be 459 256 150

        point = [x,y,z]
        print(point)
        input_points = itk.PointSet[itk.F, 3].New()
        input_points.GetPoints().InsertElement(idx, point)        
        TRANSFORMIX_POINTSET_FILE = os.path.join(self.registered_output,"transformix_input_points.txt")        
        with open(TRANSFORMIX_POINTSET_FILE, "w") as f:
            f.write("point\n")
            f.write(f"{input_points.GetNumberOfPoints()}\n")
            for idx in range(input_points.GetNumberOfPoints()):
                point = input_points.GetPoint(idx)
                f.write(f"{point[0]} {point[1]} {point[2]}\n")

        # Load Transformix Object
        transformix_object = itk.TransformixFilter.New(moving_image)
        transformix_object.SetFixedPointSetFileName(TRANSFORMIX_POINTSET_FILE)
        transformix_object.SetTransformParameterObject(result_transform_parameters)
        transformix_object.SetLogToConsole(True)
        transformix_object.SetOutputDirectory(self.registered_output)
        # Update object (required)
        transformix_object.UpdateLargestPossibleRegion()
        # Results of Transformation
        # -- Bug? -- Output is saved as .txt file in outputdirectory.
        # The .GetOutput() function outputs an empty image.
        output_transformix = transformix_object.GetOutput()
        result_point_set = np.loadtxt(os.path.join(self.registered_output, 'outputpoints.txt'), dtype='str')[:,30:33].astype('float64')
        print(output_transformix)
        print(result_point_set)

    def fill_contours(self):
        sqlController = SqlController(animal)
        # vars
        INPUT = os.path.join(self.fileLocationManager.prep, 'CH1', 'thumbnail_aligned')
        OUTPUT = os.path.join(self.fileLocationManager.prep, 'CH1', 'thumbnail_merged')
        os.makedirs(OUTPUT, exist_ok=True)
        polygon = PolygonSequenceController(animal=animal)        
        scale_xy = sqlController.scan_run.resolution
        z_scale = sqlController.scan_run.zresolution
        polygons = defaultdict(list)
        color = 0 # set it below the threshold set in mask class
        df_L = polygon.get_volume(self.animal, 3, 12)
        df_R = polygon.get_volume(self.animal, 3, 13)
        frames = [df_L, df_R]
        df = pd.concat(frames)
        len_L = df_L.shape[0]
        len_R = df_R.shape[0]
        len_total = df.shape[0]
        assert len_L + len_R == len_total, "Lengths of dataframes do not add up."

        for _, row in df.iterrows():
            x = row['coordinate'][0]
            y = row['coordinate'][1]
            z = row['coordinate'][2]
            xy = (x/scale_xy/self.scaling_factor, y/scale_xy/self.scaling_factor)
            section = int(np.round(z/z_scale))
            polygons[section].append(xy)
                    
        for section, points in tqdm(polygons.items()):
            file = str(section).zfill(3) + ".tif"
            inpath = os.path.join(INPUT, file)
            if not os.path.exists(inpath):
                print(f'{inpath} does not exist')
                continue
            img = cv2.imread(inpath, cv2.IMREAD_GRAYSCALE)
            points = np.array(points)
            points = points.astype(np.int32)
            cv2.fillPoly(img, pts = [points], color = color)
            outpath = os.path.join(OUTPUT, file)
            cv2.imwrite(outpath, img)

        files = sorted(os.listdir(INPUT))
        for file in tqdm(files):
            inpath = os.path.join(INPUT, file)
            outpath = os.path.join(OUTPUT, file)
            if not os.path.exists(outpath):
                shutil.copyfile(inpath, outpath)


    def insert_points(self):
        """This method will take the pickle file of COMs and insert them.
        The COMs in the pickle files are in pixel coordinates.
        For typical COMs, the full scaled xy version gets multiplied by 0.325 then inserted
        Upon retrieval, xy gets: divided by 0.325. Here we scale by our downsampling factor when we created the volume,
        then multiple by the scan run resolution which is hard coded below.
        """

        if not os.path.exists(self.unregistered_pickle_file):
            print(f'{self.unregistered_pickle_file} does not exist, exiting.')
            sys.exit()
        if not os.path.exists(self.registered_point_file):
            print(f'{self.registered_point_file} does not exist, exiting.')
            sys.exit()

        point_or_index = 'OutputPoint'
        source='COMPUTER'
        d = pd.read_pickle(self.unregistered_pickle_file)
        point_dict = dict(sorted(d.items()))
        controller = AnnotationSessionController(self.animal)

        with open(self.registered_point_file, "r") as f:                
            lines=f.readlines()
            f.close()

        if len(lines) != len(point_dict):
            print(f'Length {os.path.basename(self.registered_point_file)}: {len(lines)} does not match {os.path.basename(self.unregistered_pickle_file)}: {len(point_dict)}')
            sys.exit()
        print("\n\n{} points detected\n\n".format(len(lines)))
        for structure, i in zip(point_dict.keys(), range(len(lines))):        
            lx=lines[i].split()[lines[i].split().index(point_or_index)+3:lines[i].split().index(point_or_index)+6] #x,y,z
            lf = [float(x) for x in lx]
            x = lf[0] * self.um
            y = lf[1] * self.um
            z = lf[2] * self.um
            brain_region = controller.get_brain_region(structure)
            if brain_region is not None:
                annotation_session = controller.get_annotation_session(self.animal, brain_region.id, 1)
                entry = {'source': source, 'FK_session_id': annotation_session.id, 'x': x, 'y':y, 'z': z}
                controller.upsert_structure_com(entry)
            else:
                print(f'No brain region found for {structure}')

            if self.debug and brain_region is not None:
                #lf = [round(l) for l in lf]
                print(annotation_session.id, self.animal, brain_region.id, source, 
                      structure, lf, x, int(y), int(z), lx)


    def get_file_information(self):
        """Get information about the mid file in the image stack

        :return files: list of files in the directory
        :return volume_size: tuple of numpy shape
        """

        files = sorted(os.listdir(self.thumbnail_aligned))
        midpoint = len(files) // 20
        midfilepath = os.path.join(self.thumbnail_aligned, files[midpoint])
        midfile = read_image(midfilepath)
        rows = midfile.shape[0]
        columns = midfile.shape[1]
        volume_size = (rows, columns, len(files))
        return files, volume_size, midfile.dtype

    def create_volume(self):
        """Create a 3D volume of the image stack
        """
        
        files, volume_size, dtype = self.get_file_information()
        image_stack = np.zeros(volume_size)
        
        file_list = []
        for ffile in tqdm(files):
            fpath = os.path.join(self.thumbnail_aligned, ffile)
            farr = cv2.imread(fpath, cv2.IMREAD_GRAYSCALE)
            #farr = farr[200:-200,200:-200]
            file_list.append(farr)
        image_stack = np.stack(file_list, axis = 0)
        io.imsave(self.moving_volume_path, image_stack.astype(dtype))
        print(f'Saved a 3D volume {self.moving_volume_path} with shape={image_stack.shape} and dtype={image_stack.dtype}')

    def create_precomputed(self):
        chunk = 64
        chunks = (chunk, chunk, chunk)
        volumepath = os.path.join(self.registered_output, 'result.tif')
        if not os.path.exists(volumepath):
            print(f'{volumepath} does not exist, exiting.')
            sys.exit()
            
        PRECOMPUTED = self.neuroglancer_data_path
        scale = self.um * 1000
        scales = (scale, scale, scale)
        os.makedirs(PRECOMPUTED, exist_ok=True)
        volume = read_image(volumepath)
        volume = np.swapaxes(volume, 0, 2)
        num_channels = 1
        volume_size = volume.shape
        print(f'volume shape={volume.shape} dtype={volume.dtype}')
        volume = normalize16(volume)
        print(f'volume shape={volume.shape} dtype={volume.dtype}')

        ng = NumpyToNeuroglancer(
            animal,
            None,
            scales,
            "image",
            volume.dtype,
            num_channels=num_channels,
            chunk_size=chunks,
        )

        ng.init_precomputed(PRECOMPUTED, volume_size)
        ng.precomputed_vol[:, :, :] = volume
        ng.precomputed_vol.cache.flush()
        tq = LocalTaskQueue(parallel=4)
        cloudpath = f"file://{PRECOMPUTED}"
        tasks = tc.create_downsampling_tasks(cloudpath, num_mips=2)
        tq.insert(tasks)
        tq.execute()


    def check_registration(self):
        """Starter method to check for existing directories and files
        """
        status = []
        
        if os.path.exists(self.fixed_volume_path):
            status.append(f'\tFixed volume at {self.fixed_volume_path}')

        if os.path.exists(self.moving_volume_path):
            status.append(f'\tMoving volume at {self.moving_volume_path}')

        result_path = os.path.join(self.registered_output, 'result.tif')
        if os.path.exists(result_path):
            status.append(f'\tRegistered volume at {result_path}')

        reverse_transformation_pfile = os.path.join(self.reverse_elastix_output, 'TransformParameters.3.txt')
        if os.path.exists(reverse_transformation_pfile):
            status.append(f'\tTransformParameters file to register points at: {reverse_transformation_pfile}')

        if os.path.exists(self.neuroglancer_data_path):
            status.append(f'\tPrecomputed data at: {self.neuroglancer_data_path}')

        if os.path.exists(self.unregistered_pickle_file):
            status.append(f'\tCOM pickle data at: {self.unregistered_pickle_file}')

        if os.path.exists(self.unregistered_point_file):
            status.append(f'\tUnnregisted points at: {self.unregistered_point_file}')

        if os.path.exists(self.registered_point_file):
            status.append(f'\tRegisted points at: {self.registered_point_file}')


        if len(status) > 0:
            print("These are the processes that have run:")
            print("\n".join(status))
        else:
            print(f'Nothing has been run to register {self.animal} to {self.atlas} with channel {self.channel}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work on Animal')
    parser.add_argument('--animal', help='Enter the animal', required=True)
    parser.add_argument("--channel", help="Enter channel", required=False, default=1, type=int)
    parser.add_argument('--um', help="size of atlas in micrometers", required=False, default=25, type=int)
    parser.add_argument('--atlas', help='Enter the atlas: allen|princeton', required=False, default='allen')
    parser.add_argument('--orientation', help='Enter the orientation: sagittal|coronal', required=False, default='sagittal')
    parser.add_argument("--debug", help="Enter true or false", required=False, default="false")
    parser.add_argument("--task", 
                        help="Enter the task you want to perform: \
                          create_volume|register_volume|reverse_register_volume|transformix_volume|tranformix_points|create_precomputed|insert_points", 
                        required=False, default="check_registration", type=str)
    
    args = parser.parse_args()
    animal = args.animal
    channel = args.channel
    um = args.um
    atlas = args.atlas
    orientation = args.orientation
    debug = bool({"true": True, "false": False}[str(args.debug).lower()])
    task = str(args.task).strip().lower()
    volumeRegistration = VolumeRegistration(animal, channel, um, atlas, orientation, debug)


    function_mapping = {'create_volume': volumeRegistration.create_volume,
                        'register_volume': volumeRegistration.register_volume,
                        'reverse_register_volume': volumeRegistration.reverse_register_volume,
                        'transformix_volume': volumeRegistration.transformix_volume,
                        'transformix_points': volumeRegistration.transformix_points,
                        'create_precomputed': volumeRegistration.create_precomputed,
                        'check_registration': volumeRegistration.check_registration,
                        'insert_points': volumeRegistration.insert_points,
                        'create_itk': volumeRegistration.create_itk,
                        'fill_contours': volumeRegistration.fill_contours,
                        'evaluate':volumeRegistration.evaluate_registration,
                        'polygons': volumeRegistration.transformix_polygons
    }

    if task in function_mapping:
        function_mapping[task]()
    else:
        print(f'{task} is not a correct task. Choose one of these:')
        for key in function_mapping.keys():
            print(f'\t{key}')

