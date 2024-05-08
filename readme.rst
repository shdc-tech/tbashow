================
TBA Slide Show 2
================

This code is to be used on teh second TBA slide show Raspberry Pi (East monitor) - host name `tbashow2`.

The hardware differs from `tbashow1` in that it has an IR remote control sensor.

The software also differs in that it supports multiple sets of images, intended to be used for both announcements and lessons. There is no reason why this configuration could not be used on `tbashow1` as well.

The image sets are configured using `config3.json`.

As at May 2024 the software was updated to allow the web based image update to be easily disabled. This was requried because changes to the TBA website hosting arrangements blocked retrieval of the images from the server. 

In the simple mode image files are managed manually using ssh and scp. The image files are stored in directories called:

    `~/Code/SlideShow/<image_set>/local`

where `<image_set>` is the name of the image set, defined in the config file. Simple mode is enabled for an image set by not specifying a URL root parameter in the config file. If a URL root is specifed using the `URL` key, web updates will be attempted. In simple mode the conetnts for the cache and staging directories are ignored.

