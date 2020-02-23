# Intensity-RGB
Convert photo based RGB values in a .PTS point cloud file with Intensity adjusted RGB values.

Takes an input .PTS point cloud file that has photographic RGB values taken during scanning and converts the RGB values to intensity. Imported the resulting file to Autodesk Recap will allow you to then use intensity scaled point clouds in Autodesk Inventor or any other software that doesn't natively support it. 

Conversion is single threaded so may take a while until I have time to work on a multi threaded version. 

Download the .exe or alternaively run directly from the .py file with python 3.8 installed.
