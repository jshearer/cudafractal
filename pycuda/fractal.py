#!/usr/bin/python2
import os
from multiprocessing import Pool
import utils
from PIL import Image
import numpy
import argparse
from Vector import Vector
import sys
import time
import traceback
import math
import time
import locale

locale.setlocale(locale.LC_ALL, 'en_US.UTF_8')

import pycuda.driver as cuda
import pycuda.autoinit
from pycuda.compiler import SourceModule

genChunk = SourceModule("""
#include <cuComplex.h>
__global__ void gen(int size[2],float position[2],int realBlockDim[2],float *zoom,int *iterations,int *result, int* progress)
{	
	int startx = blockIdx.x*size[0];
	int starty = blockIdx.y*size[1];
	float t_x, t_y;
	int i, x, y;

	cuFloatComplex z = cuFloatComplex();
	cuFloatComplex z_unchanging = cuFloatComplex();

	float z_real, z_imag;
	for(x = startx; x < size[0]+startx; x++){
		for(y = starty; y < size[1]+starty; y++){
			atomicAdd(progress,1);
			t_x = (x+position[0])/(*zoom);
			t_y = (y+position[1])/(*zoom);

			z.x = t_x;
			z.y = t_y;
			z_unchanging.x = t_x;
			z_unchanging.y = t_y; //optomize this with pointer magic?

			for(i = 0; i<(*iterations) + 1; i++){
				z = cuCmulf(z,z);
				z = cuCaddf(z,z_unchanging); //z = z^2 + z_orig
				z_real = cuCrealf(z);
				z_imag = cuCimagf(z);
				if((z_real*z_real + z_imag*z_imag)>4){
					result[x+(y*size[0]*realBlockDim[0])] = i;
					break;
				}
			}
		}
	}
}

""").get_function("gen")
print("Compiled and got function gen")

def In(thing):
	thing_pointer = cuda.mem_alloc(thing.nbytes)
	cuda.memcpy_htod(thing_pointer, thing)
	return thing_pointer

def GenerateFractal(dimensions,position,zoom,iterations,block=(20,20,1), report=False, silent=False):
	chunkSize = numpy.array([dimensions[0]/block[0],dimensions[1]/block[1]],dtype=numpy.int32)
	zoom = numpy.float32(zoom)
	iterations = numpy.int32(iterations)
	blockDim = numpy.array([block[0],block[1]],dtype=numpy.int32)
	result = numpy.zeros(dimensions,dtype=numpy.int32)

	#Center position
	position = Vector(position[0]*zoom,position[1]*zoom)
	position = position - (Vector(result.shape[0],result.shape[1])/2)
	position = numpy.array([int(position.x),int(position.y)]).astype(numpy.float32)

	#For progress reporting:
	ppc = cuda.pagelocked_zeros((1,1),numpy.int32, mem_flags=cuda.host_alloc_flags.DEVICEMAP) #pagelocked progress counter
	ppc[0,0] = 0
	ppc_ptr = numpy.intp(ppc.base.get_device_pointer()) #pagelocked memory counter, device pointer to
	#End progress reporting

	#Copy parameters over to device
	chunkS = In(chunkSize)
	posit = In(position)
	blockD = In(blockDim)
	zoo = In(zoom)
	iters = In(iterations)
	res = In(result)

	if not silent:
		print("Calling CUDA function. Starting timer. progress starting at: "+str(ppc[0,0]))
	start_time = time.time()

	genChunk(chunkS, posit, blockD, zoo, iters, res, ppc_ptr, block=(1,1,1), grid=block)
	
	if report:
		total = (dimensions[0]*dimensions[1])
		print "Reporting up to "+str(total)+", "+str(ppc[0,0])
		while ppc[0,0] < ((dimensions[0]*dimensions[1])):
			pct = (ppc[0,0]*100)/(total)
			hashes = "#"*pct
			dashes = "-"*(100-pct)
			print "\r["+hashes+dashes+"] "+locale.format("%i",ppc[0,0],grouping=True)+"/"+locale.format("%i",total,grouping=True),
			time.sleep(0.00001)


	cuda.Context.synchronize()
	if not silent:
		print "Done. "+str(ppc[0,0])

	#Copy result back from device
	cuda.memcpy_dtoh(result, res)

	if not silent: 
		end_time = time.time()
		elapsed_time = end_time-start_time
		print("Done with call. Took "+str(elapsed_time)+" seconds. Here's the repr'd arary:\n")
		print(result)
		
	result[result.shape[0]/2,result.shape[1]/2]=iterations+1 #mark center of image
	return result

def SaveToPng(result,name):
	print("Resizing result to be in range 0-255")
	result = (result.astype(numpy.float32)*(255.0/result.max())).astype(numpy.uint8)
	print("Done resizing. Now generating image array.")

	result = result.reshape((result.shape[1],result.shape[0]))
	print("Done generating image array. Writing image file.")

	Image.fromstring("L",(result.shape[1],result.shape[0]),result.tostring()).save(name+".png")
	print("Image file written.")
