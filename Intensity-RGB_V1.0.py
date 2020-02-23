from tkinter import *
from tkinter import filedialog, scrolledtext, messagebox
import time
import math
import os
import colorsys
import threading


hsl_l = 0.7
brightness_percent = hsl_l*100
is_ready_one = False
is_ready_two = False
is_running = True

def start_buttonfunction():
	global start_time
	start_time = time.time()
	start_button.config(state = 'disabled')
	check_intensity_button.config(state = 'disabled')
	source_path_button.config(state = 'disabled')
	output_file_button.config(state = 'disabled')
	x = threading.Thread(target=process, args=(filepath,),daemon=True)
	y = threading.Thread(target=progress_size, daemon=True)
	y.start()
	x.start()

def progress_size():
	output = textbox.get("1.0",END)
	while is_running == True:
		time.sleep(1)
		source_size = os.stat(newfilepath).st_size
		size_check = (convert_size(source_size))
		textbox.delete(1.0,END)
		output_text = (output[:-1] +'Processed: ' + size_check + '\n')
		textbox.insert(INSERT, output_text)
		time.sleep(1)		

#get output file size
def convert_size(size_bytes):
   if size_bytes == 0:
       return "0B"
   size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   i = int(math.floor(math.log(size_bytes, 1024)))
   p = math.pow(1024, i)
   s = round(size_bytes / p, 2)
   return "%s %s" % (s, size_name[i])

#define the source file button behaviour
def sourceclick():
	textbox.delete(1.0,END)
	global is_ready_one
	is_ready_one = True
	global filepath
	filepath = filedialog.askopenfilename(filetypes = (("Point Cloud files","*.pts"),("all files","*.*")))
	source_entry.delete(0,END)
	source_entry.insert(0,filepath)
	source_size = os.stat(filepath).st_size
	#print(convert_size(source_size))
	textbox.insert(INSERT,f'Source file size: {convert_size(source_size)}\n')
	return

#define the output button behaviour 
def outputclick():
	global is_ready_two
	global newfilepath
	is_ready_two = True
	if is_ready_one == True and is_ready_two == True:
		start_button.config(state = 'normal')
	newfilepath = filedialog.asksaveasfilename(filetypes = (("Point Cloud files","*.pts"),("all files","*.*")))
	if newfilepath[-4:] != '.pts':
		newfilepath = newfilepath + '.pts'
	output_entry.delete(0,END)
	output_entry.insert(0,newfilepath)
	return

#global variables
max_inten = 0
min_inten = 0
max = max_inten

#Parse input file to get intensity range to set scaling factor 
def get_intensity_range(filepath):
	global max_inten
	global min_inten
	min_inten = 0
	max_inten = 0
	with open(filepath) as file_check:
		next(file_check)
		linecheckcount = 0
		for line in file_check:
			if linecheckcount <= 10000:
				#adjust intensity value
				pointline = line.split()
				floatlist = [float(x) for x in pointline]
				inten = floatlist[3]
				if inten > max_inten:
					max_inten = inten
				if inten < min_inten:
					min_inten = inten           		
				linecheckcount += 1
			else:
				break
		#print(f'Finished checking for intensity scale...max intensity: {max_inten} min intensity: {min_inten}')
		
		min_inten_entry.delete(0,END)
		min_inten_entry.insert(0,min_inten)
		max_inten_entry.delete(0,END)
		max_inten_entry.insert(0,int(max_inten))

#Convert Intensity to RGB via HSV
def process(filepath):
	global is_running
	is_running = True
	linecount_tally = 0
	window.update()
	check_inten_field = max_inten_entry.get()
	if not check_inten_field:
		get_intensity_range(filepath)
	global hsl_l
	#get fields from text entry
	hsl_l = brightness_entry.get()
	hsl_l = float(hsl_l)/100
	filepath = source_entry.get()
	newfilepath = output_entry.get()
	max_inten = float(max_inten_entry.get())
	min_inten = min_inten_entry.get()

	nfile = open(newfilepath, "w+")
	with open(filepath) as ptsfile:
		next(ptsfile)
		for line in ptsfile:
			linecount_tally += 1   
			pointline = line.split()
			floatlist = [float(x) for x in pointline]
			inten = floatlist[3]
			intenoriginal = inten
			x = floatlist[0]
			y = floatlist[1]
			z = floatlist[2]
			red = 0
			green = 0
			blue = 0
			if max_inten == 255:
				inten = inten/max_inten
			if max_inten == 2048:
				inten = (inten+max_inten)/max_inten
			if max_inten == 4096:
				inten = inten/max_inten
			rgb = colorsys.hsv_to_rgb(inten, 1, hsl_l)
			red = (int((rgb[0]*255)))
			green = (int((rgb[1]*255)))
			blue = (int((rgb[2]*255)))
			#format new line with exist x,y,z, intensity and new r,g,b
			newlineout = f"{x} {y} {z} {intenoriginal} {red} {green} {blue} \n"
			nfile.write(newlineout)
	nfile.close()
	is_running = False
	time.sleep(1)
	textbox.insert(INSERT, 'Points processed: ')
	textbox.insert(INSERT, f'{"{:,}".format(linecount_tally)}'+ '\n')
	new_size = os.stat(newfilepath).st_size
	#Calculate and display total running time      
	end_time = time.time()
	hours, rem = divmod(end_time-start_time, 3600)
	minutes, seconds = divmod(rem, 60)
	textbox.insert(INSERT, 'Processing time: ')
	textbox.insert(INSERT,("{:0>2}:{:0>2}:{:05.2f}".format(int(hours),int(minutes),seconds)))
	start_button.config(state = 'normal')
	check_intensity_button.config(state = 'normal')
	source_path_button.config(state = 'normal')
	output_file_button.config(state = 'normal')

#Define the main window
window = Tk()
window.geometry('680x200')
window.resizable(False, False)
window.title("Intensity to RGB Converter")

#set default column sizes
col_count, row_count = window.grid_size()
for col in range(col_count):
	window.grid_columnconfigure(col, minsize=0)
for row in range(row_count):
	window.grid_rowconfigure(row, minsize=20)


#Define labels, buttons and text entry
label_one = Label(window, text='Select source .PTS file:')
label_two = Label(window, text='Save output file to:')
label_three = Label(window, text='Min intensity value:')
label_four = Label(window, text='Max intensity value:')
label_five = Label(window, text='Brightness:')
#running_text = Label(window, text='')
textbox = scrolledtext.ScrolledText(window, width=35, height=8)

#Text entry boxes
source_entry = Entry(window)
output_entry = Entry(window)
min_inten_entry = Entry(window)
max_inten_entry = Entry(window)
min_inten_entry.insert(0,0)
max_inten_entry.insert(0,255)
brightness_entry = Entry(window)
brightness_entry.insert(0,brightness_percent)

#buttons
source_path_button = Button(window, text='Source path', command=sourceclick)
output_file_button = Button(window, text='Save to', comman=outputclick)
check_intensity_button = Button(window, text='Check range', command=  lambda: get_intensity_range(filepath))
start_button = Button(window, text='Start', state=DISABLED, command=lambda: start_buttonfunction())

#setup sizing adjustements
source_path_button.config(height=1, width=10)
output_file_button.config(height=1, width=10)
start_button.config(height=1, width=10)
check_intensity_button.config(height=1, width=17)
source_entry.config(width=70)
output_entry.config(width=70)

#grid setup for each element
label_one.grid(column=0, row=0, sticky=W, padx=5)
label_two.grid(column=0, row=1, sticky=W, padx=5)
label_three.grid(column=0, row=3, sticky=W, padx=5)
label_four.grid(column=0, row=4, sticky=W, padx=5)
label_five.grid(column=0, row=6, sticky=W, padx=5)
textbox.grid(column=4, row=3, columnspan=6, rowspan=4, padx=10, pady=5)
source_entry.grid(column=1, row=0, columnspan=8, padx=5)
output_entry.grid(column=1, row=1, columnspan=8, padx=5)
min_inten_entry.grid(column=1, row=3, columnspan=2, padx=5)
max_inten_entry.grid(column=1, row=4, columnspan=2, padx=5)
brightness_entry.grid(column=1, row=6, columnspan=2, padx=5)
source_path_button.grid(column=10, row=0, sticky=E, padx=5)
output_file_button.grid(column=10, row=1, sticky=E, padx=5)
check_intensity_button.grid(column=1, row=5, columnspan=2, sticky=W, padx=3)
start_button.grid(column=10, row=6, padx=5)

window.mainloop()