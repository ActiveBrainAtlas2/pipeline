### Table of contents for the pipeline process
1. [Active Brain Atlas home page](https://github.com/ActiveBrainAtlas2)
1. [Installing the pipeline software](docs/SETUP.md)
1. [A description of the pipeline process with detailed instructions](docs/PROCESS.md)
1. [HOWTO run the entire pipeline process with step by step instructions](docs/RUNNING.md)
1. [The entire MySQL database schema for the pipeline and the Django portal](schema.sql)
1. [Software design and organization](docs/Design.md)

## A high level description of the Active Brain Atlas pipeline process

The ability to view and share high resolution microsopy data among anatomists in
different labs around the world has given rise for the need for a set of tools
to perform this task. Going from tissue slides to data that can be viewed, edited
and shared is an involved process. The popular phrase "big data" comes into play
here quite visibly. Intermediary data can run around 5TB per mouse. The finished
web data will take another 5TB. This finished data also needs to be stored in
an efficient and secure format that is accessible by web servers. 

While the image data is stored on the filesystem and served by the web server,
the metadata describing the image data is stored in a database. This database
is then accessible to the web server via the database portal in use by the entire
process. Throughout the pipeline process, data is inserted, updated
and retrieved with the database. The database provides a convenient and efficent
way for multiple users anywhere in the world to create, retrieve, update, and 
delete data.  

The goal of this project is to allow labs to run this process on a cloud based or
in house server setup with low human intervention. Users will be able to go
into a web page and start, monitor and log the systems progress.

The following steps are used to process this data, from slide scanning all the 
way to web accessible data.

### Raw data processing

Each mouse brain has around 130-160 slides with 4 tissue samples on each slide.
The slides are scanned and digitized into files that contain the images and also
metadata. The images are extracted onto the filesystem and the metadata is 
inserted into the relational database. Once the metadata is in the database
and the image files have been extracted, the user(s) can perform quality control
on the data and make sure all the scenes of data are in the correct order
and any bad scenes are corrected and replaced if necessary. All this functionality
is available in the database portal. Once the quality control has finished,
the pipeline continues with the creation of images in the correct order with
high quality images. Downsampled versions of the image are also created to make
preliminary image manipulations easier and quicker to perform.


### Masking and cleaning

### Section to section alignment

### Preparation of aligned data for use in Neuroglancer