################################################################################
# General text functions

def str2bool(v):
	""" Converts a number of potential string inputs to boolean """
	import argparse 

	if isinstance(v, bool):
		return v
	if v.lower() in ('yes', 'true', 't', 'y', '1'):
		return True
	elif v.lower() in ('no', 'false', 'f', 'n', '0'):
		return False
	else:
		raise argparse.ArgumentTypeError('Boolean value expected.')


def str2int(v):
	try: 
		return int(v)
	except:
		return v


def str2float(v):
	try: 
		return float(v)
	except:
		return v


def wrap_string(string, width=60):
	"""
	Prints out a string as a set of lines with predefined width
	"""
	# Determine line breaks
	breaks = range(0,len(string), width)

	# Display lines
	for n, i in enumerate(breaks[:-1]):
		print(string[i:breaks[n+1]])

	# Edge case to display the last line
	if len(string) not in breaks:
		print(string[breaks[-1]:])

	return


def find_index(query, match): 
	""" 
	Find all instances of match in a query string or list and return their 
	indices.
	"""
	return [n for n, i in enumerate(query) if i == match]


def extract_digits(string, take_digits=True, split_string=False):
	"""
	Given a string that includes letters and numbers, will isolate the letters 
	or numbers as specified by the take_digits argument. If True, all numbers \
	will be returned. If False, all non-number characters will be returned. If 
	the split_string argument is True, will return a list of integers/strings 
	separated where the string had spaces. Otherwise, will return a single 
	integer/string.
	"""
	# Digits cases
	if take_digits: 
		# List of integers
		if split_string:
			return [str2int(x) for x in ''.join(filter(
				lambda i: i.isdigit() or i.isspace(), 
				string)).split()]
		# Single integer
		else:
			return str2int(''.join(filter(lambda i: i.isdigit(), string)))

	# Non-digits cases
	else:
		# List of strings without digits
		if split_string:
			return ''.join(filter(lambda i: not i.isdigit(), string)).split()
		# Single string without digits
		else:
			return ''.join(filter(lambda i: not i.isdigit(), string))


def split_string_at_numbers(string):
	"""
	Given a string with numbers and letters, returns a list split not at spaces, 
	but rather wherever a string of digits starts or ends. Numbers are converted
	to integers.
	"""
	# Initialize output string
	out_str = ''

	# Determine first character
	is_digit = string[0].isdigit()

	# Add each character in input to output, inserting breaks between letters 
	# and numbers
	for char in string:
		if is_digit == True:
			# Previous and current characters are both digits
			if char.isdigit():
				out_str += char
			# Previous character was digit, current character is not
			else:
				out_str += '~insert_break_here~'
				is_digit = False
				out_str += char
		else:
			# Previous character was not a digit, current character is 
			if char.isdigit():
				out_str += '~insert_break_here~'
				is_digit = True
				out_str += char
			# Previous and current characters are both not digits
			else:
				out_str += char

	return [str2int(i) for i in out_str.split('~insert_break_here~')]

################################################################################
# Protein-specific text functions

def get_aa1_list(mode='A'):
	"""
	Give a list of the 20 canonical amino acids in 1-letter form

	Mode determines the order. 
		A: alphabetical
		C: by conservative AA type cluster (see is_conservative)
	"""
	# Confirm acceptable mode choice
	mode = mode.upper()
	if mode not in ['A', 'C']:
		raise ValueError('Mode options are "A" (alphabetical) or "C" (cluster)')

	if mode == 'A':
		return ['A', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'K', 'L', 
			'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'V', 'W', 'Y']

	if mode == 'C':
		return ['A', 'F', 'I', 'L', 'M', 'V', 'W', 'Y', 
			'N', 'Q', 'S', 'T', 
			'H', 'K', 'R', 
			'D', 'E', 
			'C', 'G', 'P']
		

def get_aa3_list(mode='A'):
	"""
	Give a list of the 20 canonical amino acids in 3-letter form

	Mode determines the order. 
		A: alphabetical
		C: by conservative AA type cluster (see is_conservative)
	"""
	# Confirm acceptable mode choice
	mode = mode.upper()
	if mode not in ['A', 'C']:
		raise ValueError('Mode options are "A" (alphabetical) or "C" (cluster)')

	if mode == 'A':
		return ['ALA', 'CYS', 'ASP', 'GLU', 'PHE', 
			'GLY', 'HIS', 'ILE', 'LYS', 'LEU', 
			'MET', 'ASN', 'PRO', 'GLN', 'ARG', 
			'SER', 'THR', 'VAL', 'TRP', 'TYR']

	if mode == 'C':
		return ['ALA', 'PHE', 'ILE', 'LEU', 'MET', 'VAL', 'TRP', 'TYR', 
			'ANS', 'GLN', 'SER', 'THR', 
			'HIS', 'LYS', 'ARG', 
			'ASP', 'GLU', 
			'CYS', 'GLY', 'PRO']
		

def get_aa_dict():
	"""
	Give a dict of the 20 canonical amino acids with keys in 3-letter form and
	values in 1-letter form.
	"""
	return {'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F', 
		'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L', 'MET': 'M', 
		'ASN': 'N', 'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S', 'THR': 'T', 
		'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'}


def convert_aa_name(aa, return_orig=False):
	"""
	Takes an amino acid name and converts it from 1-letter to 3-letter or vice 
	versa, depending on input. Only works with 20 canonical amino acids.

	The return_orig option sets the response to bad input. If it is true and the
	input is not a 1-letter or 3-letter amino acid name, the original input will 
	be returned. If it is false, an error will be raised if the length is not 1 
	or 3, or if the string is not in its respective amino acid list.
	"""
	# Get sequence dict
	aa_dict = get_aa_dict()

	# If AA is 1-letter or 3-letter length, convert
	aa = aa.upper()
	if len(aa) in [1, 3]:
		# If length is 1 instead of 3, invert the aa_dict
		if len(aa) == 1:
			aa_dict = invert_dictionary(aa_dict)

		# If AA is a canonical AA, convert the name
		if aa in aa_dict:
			return aa_dict[aa]

		# If not, either return input or raise an error, as specified
		elif return_orig:
			return aa
		else:
			raise KeyError(aa)

	# If the length of input is not 1 or 3, either return input or raise an 
	# error, as specified
	else:
		if return_orig:
			return aa
		else:
			raise ValueError(
				'Amino acids must be either 1-letter or 3-letter strings')


def random_aa(seq_length, exclude_C=False):
	""" 
	Returns a string of random 1-letter amino acid names from the cannonical 
	20, to a specified length. exclude_C allows cysteines to be excluded as 
	a candidate amino acid.
	"""
	from random import randint

	aa_list = get_aa1_list()

	# Exclude cysteine
	if exclude_C:
		aa_list.remove('C')
	
	aa_string = ""
	for aa in range(seq_length):
		rand_index = randint(1, len(aa_list)) - 1
		aa_string += aa_list[rand_index]

	return aa_string


def aa_to_yeast_codon(aa_name):
	"""
	Given a 1-letter amino acid name, returns the preferred yeast codon for that 
	amino acid.
	"""
	yeast_codons={'A':'GCT', 'C': 'TGC', 'D': 'GAC', 'E': 'GAG', 'F': 'TTT', 
		'G': 'GGA', 'H': 'CAC', 'I': 'ATC', 'K': 'AAA', 'L': 'CTT', 
		'M': 'ATG', 'N': 'AAT', 'P': 'CCA', 'Q': 'CAG', 'R': 'CGT', 
		'S': 'TCA', 'T': 'ACG', 'V': 'GTA', 'W': 'TGG', 'Y': 'TAC'}

	return yeast_codons[aa_name.upper()]


def make_dna_from_peptide_sequence(peptide_sequence):
	"""
	Given a peptide sequence string using canonical amino acids, returns a yeast
	DNA string encoding it.
	"""
	dna_seq = ''

	for aa in peptide_sequence:
		dna_seq += aa_to_yeast_codon(aa)

	return dna_seq


def is_conservative(wt_aa, mut_aa):
	"""
	Input two single-letter strings representing wild type and mutant AAs.
	Returns a Boolean of whether a change from the first residue to the second
	represents a conservative substitution.
	Uses groupings of amino acids from Wikipedia:
	https://en.wikipedia.org/wiki/Amino_acid#/media/File:Amino_Acids.svg
	Staying within B, or D will be conservative. 
	Staying withing charge group in A will be conservative. 
	Any special case is nonconservative.
	"""
	res_groups = [  ['A', 'F', 'I', 'L', 'M', 'V', 'W', 'Y'],
					['C'],
					['D', 'E'],
					['G'], 
					['H', 'K', 'R'],
					['N', 'Q', 'S', 'T'],
					['P'],
					['U']]

	# Identify in which group the original residue belongs
	for rg in res_groups:
		if wt_aa in rg:
			original_group = rg
			break

	# Check whether the substituted residue is in the same group
	conservation = mut_aa in original_group

	return conservation

################################################################################
# List manipulation functions

def join_list(item_list, joiner=''):
	"""
	Convert a list into a string of items. By default, there will be nothing 
	between joined items, though different joiner strings can be used. List
	does not need to be converted to strings first.
	"""
	return joiner.join([str(i) for i in item_list])


def partition_list(in_list, partitions, member):
	"""
	Given a list, a number of partitions, and a partition member number,
	splits the list into the appropriate number of partitions, and returns 
	the specified member. Member should be 1-indexed, so the minimum is 1 and
	maximum is the number of partitions.
	"""
	# Confirm appropriate member number
	assert 1 <= member <= partitions

	# Determine list length and partition size
	list_size = len(in_list)
	partition_size = int(list_size/partitions)
	overrun = list_size % partitions

	# Determine starting index to collect. If the list doesn't break into equal 
	# partitions, the earlier partitions will have one extra element
	start_index = (member - 1) * partition_size
	if member > overrun:
		start_index += overrun
	else:
		start_index += member - 1

	# Determine end index to collect
	end_index = start_index + partition_size
	if member <= overrun:
		end_index += 1

	return in_list[start_index:end_index]


def flatten_nested_lists(in_list, sort=True, nonredundant=True):
	"""
	Takes a list of lists and flattens it into a single list. Can optionally 
	remove redundant entries (this is the default behavior).
	"""
	# Make flattened list
	flat_list = [item for sublist in in_list for item in sublist]

	# Sort the list if desired
	if sort:
		flat_list.sort()

	# Remove redundancies
	if nonredundant:
		non_redundant_list = []
		for item in flat_list:
			if item not in non_redundant_list:
				non_redundant_list.append(item)
		return non_redundant_list
	else:
		return flat_list


def variable_sliding_window(inp, min_size=0, max_size=0):
    """
    Takes a string or list input and returns a list of frames in that input. The 
    frame size increases with each iteration. Thus, running on an input of 'str' 
    with produce the output ['s', 't', 'r', 'st', 'tr', 'str']. Default behavior 
    will go from a frame size of 1 up to the full size of the input. Optionally, 
    this can be constrained to a set window size range. 
    """
    # Initialize output list
    out_windows_list = []

    # Set initial window size
    if min_size:
        window_size = min_size
    else:
        window_size = 1

    # Set final window size
    if max_size:
        window_max = max_size
    else:
        window_max = len(inp) + 1

    # Outer loop with increasing window size
    while window_size <= window_max:
        frame_start = 0
        frame_end = frame_start + window_size

        # Inner loop sliding the window
        while frame_end <= len(inp):
            # Add frame to output list
            out_windows_list.append(inp[frame_start:frame_end])

            # Increment start of frame and end of frame
            frame_start += 1
            frame_end = frame_start + window_size

        # Increment window size
        window_size += 1

    return out_windows_list	


def find_nearest_in_array(array, value, greater=False, lesser=False):
	"""
	Find the index of the closest value in an array to a query value. The
	array does not need to be sorted. By default, selects either greater or 
	lesser, whichever is closest. greater or lesser can be set to true (not 
	both) to force one direction.
	"""
	import numpy as np

	assert not (greater == True and lesser == True)

	# Convert input into a numpy array (might be a list, etc)
	array = np.asarray(array)

	# Take differences
	difs_array = array - value

	# If seeking nearest greater, exclude negatives
	if greater:
		difs_array = np.where(difs_array > 0, difs_array, np.inf)

	# If seeking nearest lesser, exclude positives
	if lesser:
		difs_array = np.where(difs_array < 0, difs_array, np.inf)

	# If no nearest value is found, return None
	if all(np.isinf(difs_array)):
		return None

	# Return the index of the nearest value
	return (np.abs(difs_array)).argmin()


def invert_dictionary(dictionary):
	"""
	Takes a dict object and makes a copy where the values of the input are the 
	keys of the output and vice versa. 
	"""
	return {v: k for k, v in dictionary.items()}

################################################################################
# Math functions

def ceilm(number, multiple):
    """
    Returns a float rounded up by a factor of the multiple specified
    """
    from math import ceil

    return ceil(float(number) / multiple) * multiple


def floorm(number, multiple):
    """
    Returns a float rounded down by a factor of the multiple specified
    """
    from math import floor

    return floor(float(number) / multiple) * multiple


def roundm(number, multiple):
    """
    Returns a float rounded to a factor of the multiple specified
    """
    return round(float(number) / multiple) * multiple


def opt_r2(data_column, gmm, min_bins=5, max_bins=1000):
	"""
	Given a 1-dimensional set of data and a gaussian model that fits it, cycles 
	through a range of bin counts (default 5-1000) to determine the bin count 
	that yields the best R2 value, and returns that R2 value and the bin count.
	"""
	import numpy as np
	from sklearn.metrics import r2_score

	best_i = min_bins
	best_r2 = -10
	for i in range(min_bins, max_bins):
		x = np.linspace(data_column.min(), data_column.max(), i)
		y1 = np.histogram(data_column, bins=i)[0]
		y1_norm = np.linalg.norm(y1)
		y2 = np.exp(gmm.score_samples(x.reshape(-1, 1)))
		r2 = r2_score(y1/y1_norm, y2)
		if r2 > best_r2:
			best_i = i
			best_r2 = r2
	return best_r2, best_i


def gaussfit(x_array, y_array, components=1):
	"""
	Normal/gaussian mixtures fitting of data. Fits a model with a specified 
	number of gaussian components to the y_array data with range and resolution 
	specified by the x_array (which is usually a numpy.linspace). Returns the 
	model and a dataframe with the parameter values.
	"""
	import numpy as np
	import pandas as pd
	from sklearn.mixture import GaussianMixture

	# Fit model
	gmm = GaussianMixture(n_components=components).fit(X=y_array)
	gmm_y = np.exp(gmm.score_samples(x_array.reshape(-1, 1)))
	
	# Collect fit parameters
	gmm_params = {}	
	for i in range(components):
		gmm_params['μ' + str(i + 1)] = [np.reshape(gmm.means_, components)[i]]
		gmm_params['σ' + str(i + 1)] = [np.reshape(gmm.covariances_, components)[i]]
		gmm_params['wt' + str(i + 1)] = [np.reshape(gmm.weights_, components)[i]]
	gmm_params['R2'] = [opt_r2(y_array, gmm)[0]]
	gmm_params = pd.DataFrame(gmm_params)

	return gmm_y, gmm_params


def sum_squares(array):
	"""
	Calculates the sum of squares for all values in an array
	"""
	return sum(i ** 2 for i in array)


def interquartile_bounds(array):
	"""
	For a given array, calculates the boundaries for outlier classification, 
	based on being more than 1.5 * (interquartile range) above or below the 
	quartiles. Returns lower and upper bounds.
	"""
	import numpy as np

	# Determine quartiles
	q1 = np.percentile(array, 25, interpolation='midpoint')
	q3 = np.percentile(array, 75, interpolation='midpoint')

	# Determine interquartile range
	iqr = q3 - q1

	# Determine bounds
	lower = q1 - 1.5 * iqr
	upper = q3 + 1.5 * iqr
	return lower, upper


def calc_distance(c1, c2):
	""" 
	Returns the distance between two XYZ coordinate vectors
	"""
	import numpy as np

	return np.linalg.norm(np.array(c1) - np.array(c2))


def calc_angle(c1, c2, c3):
	"""
	Calculate the angle between three points, about the middle point, c2

	Returns value in degrees
	"""
	import numpy as np

	# Get triangle legs
	l1 = np.array(c1) - np.array(c2)
	l2 = np.array(c3) - np.array(c2)

	# Determine angle
	cosine_angle = np.dot(l1, l2) / (np.linalg.norm(l1) * np.linalg.norm(l2))
	angle = np.arccos(cosine_angle)

	return np.degrees(angle)


def calc_dihedral(c1, c2, c3, c4):
	"""
	Calculate the dihedral/torsion angle between four points

	Returns value in degrees
	"""
	import numpy as np

	# Get dihedral vectors
	v1 = np.array(c1) - np.array(c2)
	v2 = np.array(c2) - np.array(c3)
	v3 = np.array(c3) - np.array(c4)

    # 



################################################################################
# General file reading and editing 

def readfile(file_name):
	""" Opens a file in read-mode and returns a list of the text lines """
	with open(file_name, 'r') as r:
		lines = r.readlines()

	return lines


def is_zipped(fi):
	"""
	Check whether the end of the file extension is '.gz'. Returns a boolean.
	"""
	from os.path import splitext

	return bool(splitext((fi))[-1] == '.gz')


def unzip_file(fi):
	""" 
	Read in a gzipped file and save an unzipped version, stripping off .gz 
	from the file name ending, and returning that rename.
	"""
	import subprocess

	if is_zipped(fi):
		# Unzip the file
		subprocess.call(['gunzip', fi])

		# Remove .gz from filename
		fi = fi.rstrip('.gz')
	else:
		print('Warning: File is not zipped: \n{}'.format(fi))

	return fi


def zip_file(fi):
	""" 
	Read in an unzipped file and save compress it, adding .gz to the file name 
	ending, and returning that rename.
	"""
	import subprocess

	if not is_zipped(fi):
		# Unzip the file
		subprocess.call(['gzip', fi])

		# Add .gz to filename
		fi = fi + '.gz'
	else:
		print('Warning: File is already zipped: \n{}'.format(fi))

	return fi


def gzip_file(infile, outfile):
    """ gzips a file """
    import gzip

    with open(infile, 'rb') as f_in:
        with gzip.open(outfile, 'wb') as f_out:
            f_out.writelines(f_in)
    
    return outfile


def unzip_gz(infile, outfile):
    """ Unzips a gzip file """
    import gzip
    import shutil

    with gzip.open(infile, 'rb') as f_in:
        with open(outfile, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    return outfile


def find_maybe_compressed_file(fi, gunzip=False, gzip=False):
	"""
	Given a filename and path for a file that may be gzipped, returns a filename
	correcting for a .gz extension. Can unzip of zip the file if desired, in 
	which case the name will correspond to the desired condition of the file.
	"""
	from os.path import isfile

	# Input name is correct
	if isfile(fi):
		outname = fi

	# Input name is uncompressed, file is compressed
	elif isfile(fi + '.gz'):
		outname = fi + '.gz'

	# Input name is compressed, file is uncompressed
	elif isfile(fi.rstrip('.gz')):
		outname = fi.rstrip('.gz')

	# File wasn't found either way
	else:
		err_text = 'Cannot find this file (zipped or unzipped): \n{}'
		raise ValueError(err_text.format(fi))
	
	# Unzipping
	if gunzip and ('.gz' in outname):
		outname = unzip_file(outname)

	# Zipping
	if gzip and ('.gz' not in outname):
		outname = zip_file(outname)

	return outname


def copy_file(input_filename, output_filename, gunzip=False, gzip=False):
	"""
	Copies a file. Differs from default shutil copyfile in that there is a check
	for whether the file is zipped, and options to zip or unzip it.
	"""
	from shutil import copyfile

	# Get input file
	input_filename = find_maybe_compressed_file(
		input_filename, gunzip=gunzip, gzip=gzip)

	# Make sure input and output zipped conditions match
	if not is_zipped(input_filename) and is_zipped(output_filename):
		output_filename = output_filename.rstrip('.gz')

	if is_zipped(input_filename) and not is_zipped(output_filename):
		output_filename = output_filename + '.gz'

	copyfile(input_filename, output_filename)

	return output_filename


def move_file(input_filename, output_filename, gunzip=False, gzip=False):
	"""
	Moves a file. Differs from default shutil move in that there is a check
	for whether the file is zipped.
	"""
	from shutil import move

	# Get input file
	input_filename = find_maybe_compressed_file(
		input_filename, gunzip=gunzip, gzip=gzip)

	move(input_filename, output_filename)

	return output_filename


def delete_file(file_name):
	""" Deletes a file """
	from os import remove

	remove(find_maybe_compressed_file(file_name))

	return


def out_directory(directory_name):
	"""
	Given an output directory string, checks whether that directory exists.  
	Creates it if it doesn't. If no name is given, returns an empty string.
	"""
	from os import makedirs
	from os.path import isdir

	if directory_name:
		if not isdir(directory_name):
			makedirs(directory_name)
		return directory_name
	else:
		return ''


def output_file_name(filename, path='', extension='', 
	prefix=None, suffix=None, mkdir=True, dont_strip_gz=False):
	"""
	Given a filename, can add prefix, suffix, and/or path to the filename.
	If the input file includes a path, that path will be retained by default 
	(an empty string) unless a but can be set to a value or changed to None. The
	same is true of the file extension. Detection of file extension locates the 
	last period (.), so that is where suffixes will be added, though .gz 
	extensions will be stripped off by default. Prefixes and suffixes will be 
	appended with underscores (_). If mkdir is True and the path does not exist, 
	it will be created, assuming that there is a path.
	"""
	from os.path import basename, dirname, join, splitext

	# Remove .gz ending
	if not dont_strip_gz:
		filename = filename.rstrip('.gz')

	# Get file path, basename, and extension
	pathname = dirname(filename)
	outname, ext = splitext(basename(filename))

	# Overwrite path if given a user input, or set to default, or leave empty
	if path:
		pathname = path
	elif isinstance(path, str) and not path:
		pathname = pathname
	else:
		pathname = ''

	# Create directory if it doesn't exist
	if mkdir and pathname != '':
		pathname = out_directory(pathname)

	# Add prefix
	if prefix != None:
		outname = '_'.join([str(prefix), outname])

	# Add suffix
	if suffix != None:
		outname = '_'.join([outname, str(suffix)])

	# Overwrite extension if given a user input, or set to default, or leave
	if extension:
		outname = '.'.join([outname, extension])
	elif isinstance(extension, str) and ext != '':
		outname = '.'.join([outname, ext.lstrip('.')])

	return join(pathname, outname)

################################################################################
# Fasta functions (many functions require BioPython)

def parse_fastafile(fasta_file):
	"""
	Read in a file with a list of fasta sequences and return a list of biopython
	SeqRecord objects for all sequences
	"""
	from Bio import SeqIO

	# Initialize list
	fasta_list = []

	# Populate list
	for r in SeqIO.parse(fasta_file, 'fasta'): 
		fasta_list.append(r)

	return fasta_list


def global_align(seq1, seq2, one_alignment_only=False, id_reward=1,  
	mismatch_penalty=-0.2, open_gap_penalty=-2, extend_gap_penalty=-0.1,  
	penalize_end_gaps=False, score_only=False):
	"""
	Performes a global alignment using Biopython's pairwise2 tool. 
	"""
	from Bio import pairwise2

	return pairwise2.align.globalms(
		seq1, seq2, id_reward, mismatch_penalty, open_gap_penalty, 
		extend_gap_penalty, penalize_end_gaps=penalize_end_gaps, 
		score_only=score_only, one_alignment_only=one_alignment_only)


def generate_formatted_aligment(alignment, full=True):
	"""
	Input a biopython alignment to generate a formatted alignment display.
	Full means that the full sequence will be included, not just the aligned 
	portion.
	"""
	from Bio.pairwise2 import format_alignment
	
	# Generate alignment string
	alignment_string = format_alignment(*alignment, full_sequences=full)

	return alignment_string


def split_alignment_string(alignment_string, check_len=True):
	"""
	Strings output by biopython's format_alignment function are often more 
	convenient as a list than as a string. This function  splits the string out
	and then checks that all sequences are consistent in length. The first three 
	items in the list are respectively the query sequence, the identity between 
	sequences, and the subject sequence. 
	"""
	# Split into sections
	alignment_list = alignment_string.split('\n')

	# Confirm that all sequences are consistent length
	if check_len:
		try:
			assert len(alignment_list[0]) == len(alignment_list[1]) 
			assert len(alignment_list[0]) == len(alignment_list[2])
		except AssertionError:
			d = {0: 'query', 1: 'identity', 2: 'subject'}
			print('Sequences were not the same length')
			for i in range(3):
				print(d[i])
				print(len(alignment_list[i]))
				print(alignment_list[i])
				print()
			raise

	return alignment_list


def display_alignment(alignment, width=80):
	"""
	Input a biopython alignment to print out a formatted alignment display.
	Setting width value will change the number of characters per line of 
	output display. 
	"""
	from math import ceil

	# Generate alignment string
	alignment_string = generate_formatted_aligment(alignment, full=True)

	# Split alignment string into sections representing different sequences
	a_list = split_alignment_string(alignment_string)
	
	# Determine number of linebreaks for display
	str_len = len(a_list[0])
	num_breaks = ceil(str_len/width)

	# Display sequence
	first_seq_pos = 0
	second_seq_pos = 0
	for n in range(num_breaks):
		# Calculate break points
		start = n * width
		end = (n + 1) * width

		# Determine non-gap sequence lengths
		first_seq_len = len([i for i in a_list[0][start:end] if i != '-'])
		second_seq_len = len([i for i in a_list[2][start:end] if i != '-'])

		# Initialize sequence positions
		if first_seq_pos == 0 and first_seq_len > 0:
			first_seq_pos += 1
		if second_seq_pos == 0 and second_seq_len > 0:
			second_seq_pos += 1

		print(first_seq_pos)
		for i in range(3):
			print(a_list[i][start:end])
		print(second_seq_pos)
		print('')

		# Increment sequence positions (excluding gaps)
		first_seq_pos += first_seq_len
		second_seq_pos += second_seq_len

	# Display other alignment attributes
	for i in a_list[3:]:
		print(i)

	return


def tabulate_sequence_alignment(alignment):
	"""
	Input a biopython alignment to generate a pandas dataframe including the 
	sequence numbers and letters at each position and identity and alignment 
	columns, denoted by integers.
	"""
	import pandas as pd
	import numpy as np

	# Generate alignment string
	alignment_string = generate_formatted_aligment(alignment, full=True)

	# Split alignment string into sections representing different sequences
	a_list = split_alignment_string(alignment_string)
	s1, ident, s2 = a_list[:3]

	# Create positions lists for both sequences
	seq_positions = {}
	for n, seq in enumerate([s1, s2]):
		s_positions = []
		s_val = 0
		for i in list(seq):
			if i == '-':
				s_positions.append(np.nan)
			else:
				s_val += 1
				s_positions.append(s_val)
		seq_positions[n] = s_positions

	# Create identity list
	identities = []
	for i in list(ident):
		if i == '|':
			identities.append(1)
		else:
			identities.append(0)
	        
	# Make table
	align_df = pd.DataFrame({
		's1_position': seq_positions[0],
		's1_sequence': list(s1),
		's2_position': seq_positions[1],
		's2_sequence': list(s2),
		'identity': identities})

	# Add column to check whether residues are aligned 
	align_df['aligned'] = align_df.apply(lambda row: int(
		isinstance(row['s1_position'], int) and 
		isinstance(row['s2_position'], int)), axis='columns')

	return align_df


def seq_to_seqrecord(seq, seqrecord):
	"""
	Given a biopython Seq object and a reference SeqRecord object, converts the
	Seq to a SeqRecord, copying the naming parameters from the reference.
	"""
	from Bio.SeqRecord import SeqRecord

	return SeqRecord(seq, id=seqrecord.id, name=seqrecord.name, 
		description=seqrecord.description, dbxrefs=seqrecord.dbxrefs)


def extract_matching_region(query_seq, subject_seq):
	"""
	Given a larger query sequence (a biopython SeqRecord object) that contains 
	a target subject sequence region, extracts that portion of the query. 
	Returns a SeqRecord.
	"""
	# Align query and subject
	alignment = global_align(query_seq.seq, subject_seq, 
		one_alignment_only=True)[0]

	# Generate strings for each sequence and the identity
	alignment_string = generate_formatted_aligment(alignment, full=True)
	q_str, i_str, s_str, _, _ = split_alignment_string(alignment_string)

	# Determine aligned region
	aligned_indices = [n for n, i in enumerate(i_str) if i != ' ']

	# If there is no aligned region, return an empty record
	if len(aligned_indices) == 0:
		return seq_to_seqrecord('X', query_seq)

	# Determine end indices of aligned region
	start = min(aligned_indices)
	end = max(aligned_indices) + 1

	# Extract matching part of sequence 
	query_subsequence = query_seq.seq[start: end]

	# Convert back to a sequence record
	return seq_to_seqrecord(query_subsequence, query_seq) 


def translate_dna_fasta(fasta_file, forward=True, reverse=True, 
	include_frame=False, to_stop=False, largest_seq=False, ref_seq=None, 
	ref_all_frames=False, extract_matching=False):
	"""
	With an input fasta file with DNA sequences, translates the DNA sequences 
	into amino acid sequences.
	
	By default, will generate all three reading frames for both forward and 
	reverse sequence, and will continue translating past stop codons. Options 
	forward and reverse can be turned false to limit translation direction.

	Setting to_stop as true will result in translation stopping at the first 
	stop codon. The largest_seq option is intended to work with to_stop, so 
	only the translations of the longest open reading frames for each sequence 
	are returned.

	Providing a ref_seq is an alternative way to select only one translation, 
	selecting only the one which has the best match to the reference. Calls the
	global_align function with default settings to determine which translation
	that is. When sequences are bad and frame shifts may have occurred, the
	ref_all_frames option may be used to prevent reduction to only one 
	translation, but rather to take the reference portion from all frames.

	If extract_matching is true and req_seq is provided, only the portion of 
	the translated sequence that aligns with the reference sequence will be 
	returned.
	"""
	# Initialize collection list
	all_aa_records = []

	# Read all DNA records in the fasta file
	for dna_record in parse_fastafile(fasta_file):
		# Get forward and reverse-complement DNA sequences
		dna_sequences = {}
		if forward:
			dna_sequences['forward'] = dna_record.seq
		if reverse:
			dna_sequences['reverse'] = dna_record.seq.reverse_complement()

		# Perform translations for all frames
		aa_records = []
		for s in dna_sequences:
			for i in range(3):
				# Translate
				aa_seq = dna_sequences[s][i:].translate(to_stop=to_stop)

				# Convert to sequence record with description including 
				# direction and frame
				aa_record = seq_to_seqrecord(aa_seq, dna_record)
				if include_frame or ref_all_frames:
					aa_record.description += "|{}|frame {}".format(s, i)

				# Add to translations list for this DNA record
				aa_records.append(aa_record) 

		# Only add longest sequence if to_stop and largest_seq are True 
		if to_stop and largest_seq:
			all_aa_records.append(max(aa_records, key=len))

		# Only add sequence with best match to reference if ref_seq is given 
		# and ref_all_frames is False
		elif ref_seq and not ref_all_frames:
			align_scores = [global_align(s.seq, ref_seq, score_only=True, 
				one_alignment_only=True) for s in aa_records]
			best_s, best_i = max([[s, i] for i, s in enumerate(align_scores)])
			all_aa_records.append(aa_records[best_i])

		# Add translated records to collection list if no filter is given
		else:
			all_aa_records += aa_records

	# Extract matching region of sequences if extract_matching is True and 
	# ref_seq is given
	if extract_matching and ref_seq:
		all_aa_records = [extract_matching_region(a, ref_seq) for 
			a in all_aa_records]

	return all_aa_records


def write_fastafile(sequence_records, write_file):
	"""
	Given a list of biopython sequence records, writes them to a text file.
	"""
	from Bio import SeqIO

	with open(write_file, 'w') as w:
		for sr in sequence_records:
			SeqIO.write(sr, w, 'fasta')
			w.write('\n')

	return


def compare_sequences(seq1, seq2, first_res=1, repair=False, only_difs=False,
	make_subs_column=False):
	"""
	Given two sequence strings that this function assumes are similar, produces 
	an aligned table from from which it is easy to identify the sites where the 
	second sequence differs from the first, or where residues were sequenced 
	badly (X). Returns a dataframe of sites. The columns in the dataframe are 
	the seq_1 letter, the seq_2 letter, with the row index matching the first 
	sequence. 

	The first letter in the first seqence is assumed to be residue 1 by default, 
	but chan be changed with the first_res option. 

	If the repair option is set to True, then any X values in the second 
	sequence will be replaced with the letter of the aligned residue, similar to 
	homologous recombination repair. 

	If the only_difs option is set to True, only the subset of the dataframe 
	that includes changes in sequence will be returned. X values will be counted 
	as sequence differences. 

	If the make_subs_column option is set to True in addition to only_difs, adds  
	an extra column with the substitution in the form [seq1 AA][site][seq2 AA].
	"""
	import numpy as np
	import pandas as pd

	# Align the sequences. 
	alignment = global_align(seq1, seq2, one_alignment_only=True)[0]
	a_seq1 = alignment[0]
	a_seq2 = alignment[1]

	# Create single-sequence dataframes with correct indexing 
	s1_table = pd.DataFrame({'seq1': list(seq1)})
	s1_align_ind = [n for n, i in enumerate(a_seq1) if i != '-']
	correction = first_res - s1_align_ind[0]
	s1_table.index = np.array(s1_align_ind) + correction

	s2_table = pd.DataFrame({'seq2': list(seq2)})
	s2_align_ind = [n for n, i in enumerate(a_seq2) if i != '-']
	s2_table.index = np.array(s2_align_ind) + correction

	# Merge into an aligned table with correct indexing
	aligned_table = pd.concat([s1_table, s2_table], axis=1)

	# Repair bad sequences (X values)
	if repair:
		aligned_table['seq2'] = np.where(aligned_table['seq2'] == 'X', 
			aligned_table['seq1'], aligned_table['seq2'])

	# Isolate changes
	if only_difs:
		masks = (aligned_table['seq1'].notna())
		masks = masks & (aligned_table['seq2'].notna())
		masks = masks & (aligned_table['seq1'] != aligned_table['seq2'])
		aligned_table = aligned_table[masks]

		if make_subs_column:
			if len(aligned_table) > 0:
				aligned_table['substitution'] = aligned_table.apply(lambda row: 
					''.join([row['seq1'], str(row.name), row['seq2']]), 
					axis='columns')
	
	return aligned_table

################################################################################
# PDB informatics functions

def collect_pdbs_list(target_dir, sort=True):
	"""
	Uses glob to collect all .pdb and .pdb.gz files in a directory. 
	"""
	from glob import glob
	from os.path import join

	all_pdbs = glob(join(target_dir, '*.pdb'))
	all_pdbs += glob(join(target_dir, '*.pdb.gz'))
	all_pdbs += glob(join(target_dir, '*.ent'))
	all_pdbs += glob(join(target_dir, '*.ent.gz'))

	if sort:
		all_pdbs.sort()

	return all_pdbs


def check_decoy_counts(decoy_dir, decoy_name_list, decoy_count):
	"""
	Given a list of base names and an expected decoy count, returns a list of 
	names that didn't run at all and a dict of names with how many decoys short
	of the expected count they are.
	"""
	from glob import glob 

	# Initialize collection lists
	pdbs_that_didnt_process = []
	pdbs_missing_decoys = {}

	# Iterate through decoy name list, checking decoy counts
	for dec_name in decoy_name_list:
		# Collet list of all decoys with the given base name
		decoys = glob(output_file_name(dec_name, path=decoy_dir, 
			extension='pdb', suffix='*'))

		# If the list is empty, add to the didnt_process list
		if len(decoys) == 0:
			pdbs_that_didnt_process.append(dec_name)
			continue

		# If the list is incomplete, add to the missing_decoys dict
		if len(decoys) != decoy_count:
			missing_decs[dec_name] = decoy_count - len(decoys)


	return pdbs_that_didnt_process, pdbs_missing_decoys


def fix_pdb(pdb, extension=None, clobber=False):
	"""
	Cleans up a PDB file, stripping out LINK lines and changing enzdes headers 
	so that constraints won't crash. Overwrites the original with the cleaned 
	version. An extension option may be given that will allow for the insertion 
	of extra residues into a chain. This extension must be in the format of 
	[chain_modified, modification_start, altered_length], ex ['A', 96, 5]
	"""
	# Unzip and open the PDB
	pdb = find_maybe_compressed_file(pdb, unzip_file=True)
	with open(pdb, 'r') as r:
		lines = r.readlines()

	# Collect lists of LINK lines, enzdes header lines, and range of atom lines
	link_lines = []
	enzdes_lines = []
	first_atom = 0
	last_atom = 0
	for n, line in enumerate(lines):
		# Link lines
		if 'LINK' in line:
			link_lines.append(n)

		# Enzdes lined
		if 'REMARK 666' in line:
			enzdes_lines.append(n)

		# Atom lines range
		if 'ATOM' in line and first_atom == 0:
			first_atom = n
		if 'ATOM' in line and n > last_atom:
			last_atom = n

	# Remove LINK lines, which interfere with putting in constraints
	for l2r in link_lines:
		lines[l2r] = '\n'

	# Fixing enzdes comments block so comments match (mutated) PDB sequence
	for eline in enzdes_lines:
		line_text = lines[eline]
		# Splitting into columns. Columns 4-6 refer to the first residue, and 
		# columns 9-11 refer to the second residue
		e_columns = line_text.split()

		# Checking whether enzdes constraint headers match sequence in PDB
		for e_chain, e_aa, e_res in [e_columns[4:7], e_columns[9:12]]:
			orig_text = ' '.join([e_chain, e_aa, e_res])

			# Addressing extension
			if extension:
				ext_chain, ext_start, ext_len = extension
				if e_chain == ext_chain and int(e_res) > ext_start:
					e_res = str(int(e_res) + ext_len)
					correct_text = ' '.join([e_chain, e_aa, e_res])
					line_text = line_text.replace(orig_text, correct_text)

			# Looping through all ATOM lines in the PDB until finding the 
			# right residue, then checking agreement and stopping loop
			for atom_line in lines[first_atom: last_atom]:
				# Skip any line that isn't an atom line, such as a TER
				if ('ATOM' not in atom_line):
					continue

				# Splitting into columns. Column 4 is the chain, column 5 is 
				# the residue number, column 3 is the aa name
				a_columns = atom_line.split()
				a_aa, a_chain, a_res = a_columns[3:6]

				# Skip until finding the right residue in the right chain
				if (a_chain != e_chain) or (a_res != e_res):
					continue

				# If the enzdes header and PDB agree, stop there
				if e_aa == a_aa:
					break

				# If the enzdes header and PDB disagree, correct the header
				else:
					correct_text = ' '.join([a_chain, a_aa, a_res])
					line_text = line_text.replace(orig_text, correct_text)
					break

		# Setting header line with corrected text
		lines[eline] = line_text
		
	# Saving corrected PDB
	if clobber:
		with open(pdb, 'w') as w:
			w.writelines(lines)
	else:
		with open(pdb.replace('.pdb', '_corrected.pdb'), 'w') as w:
			w.writelines(lines)

	return


def extract_pdb_atom_lines(pdb, het=False, enzdes=False, 
	link=False, connect=False):
	"""
	Reads a PDB file and extracts the ATOM lines. By default, only ATOM lines 
	are collected. However, if het is set to True, all HETATM lines will also be
	collected. If het is a list of strings (case-sensitive), only the HETATM 
	lines including those residue types will be collected with the ATOM lines.
	If enzdes is True, REMARK 666 lines will also be collected. If link is True,
	LINK lines will also be collected. If connect is True, CONNECT lines will 
	also be collected.
	"""
	# Read in the PDB file
	with open(pdb, 'r') as r:
		pdb_lines = r.readlines()

	# Go through lines, collecting only the 
	pdb_extract = []
	for line in pdb_lines:
		# Collect ATOM lines
		if line[:4] == 'ATOM':
			pdb_extract.append(line)
			continue

		# Collect HETATM lines
		if het:
			if line[:6] == 'HETATM':
				if not isinstance(het, list):
					pdb_extract.append(line)
					continue
				else:
					for atype in het:
						if atype in line:
							pdb_extract.append(line)
							break

		# Collect enzdes lines
		if enzdes:
			if line[:10] == 'REMARK 666':
				pdb_extract.append(line)
				continue

		# Collect LINK lines
		if link:
			if line[:4] == 'LINK':
				pdb_extract.append(line)
				continue

		# Collect enzdes lines
		if connect:
			if line[:6] == 'CONECT':
				pdb_extract.append(line)
				continue
	return pdb_extract


def tabulate_pdb_atom_lines(pdb, het=False):
	"""
	Generates a pandas dataframe from a PDB's ATOM lines. Can include HETATM as 
	well.
	"""
	import pandas as pd

	# Extract PDB ATOM/HETATM lines
	atom_lines = extract_pdb_atom_lines(pdb, het=het)

	# Define columns
	pdb_atom_cols = {'type': (0, 6), 'atom_number': (6, 11), 
		'atom_name': (12, 16), 'alt_location': (16, 17), 'res_name': (17, 20), 
		'chain_id': (21,22), 'res_number': (22, 27), 'x': (30, 38), 
		'y': (38, 46), 'z':(46,54), 'occupancy': (54, 60), 
		'b-factor': (60, 66), 'segment': (72, 76), 'element': (76, 80)}

	# Create data frame
	atom_table = pd.DataFrame([])
	for atom_line in atom_lines:
		atom_dict = {}
		for col, ind in pdb_atom_cols.items():
			atom_dict[col] = atom_line[ind[0]:ind[1]].strip()
		atom_table = atom_table.append(atom_dict, ignore_index=True)

	# Convert columns from strings to numeric where appropriate
	for col in ['atom_number', 'res_number']:
		atom_table[col] = atom_table[col].astype(int, errors='ignore')
	for col in ['x', 'y', 'z', 'b-factor', 'occupancy']:
		atom_table[col] = atom_table[col].astype(float)

	return atom_table


def get_pdb_sequences(pdb_atom_table):
	"""
	Given a PDB atom table from tabulate_pdb_atom_lines, generates a dict of 
	chains and their sequences
	"""
	# Extract CA-only table to read sequence
	ca_table = pdb_atom_table[pdb_atom_table['atom_name'] == 'CA']

	# Create dict of chains and sequences
	chains_sequences = {}

	# Iterate through all chains to collect sequences
	for chain in ca_table['chain_id'].unique():
		chain_ca_table = ca_table[ca_table['chain_id'] == chain]
		sequence = ''.join(
			[convert_aa_name(i) for i in chain_ca_table['res_name']])
		chains_sequences[chain] = sequence
	
	return chains_sequences


def find_aa_in_pdb_atom_table(atom_table, chain, pdb_number, aa1=True):
	"""
	From a PDB atom table like those generated by tabulate_pdb_atom_lines, find 
	the amino acid name for the residue of specified chain and number. The aa1 
	option will control whether the 1-letter (True) or 3-letter (False) name 
	will be returned.
	"""
	# Isolate the CA of the desired residue
	target_ca = atom_table[(atom_table['atom_name'] == 'CA') & 
		(atom_table['chain_id'] == chain) & 
		(atom_table['res_number'] == pdb_number)]

	# Get the residue name
	res_name = target_ca['res_name'].to_string(index=False).strip()

	# Outpur the residue name in desired form
	if aa1:
		return convert_aa_name(res_name)
	else:
		return res_name


def check_pdb_atom_table_contiguity(atom_table, min_res=1, max_res=0):
	"""
	PDB files may include missing residues or insertion residues (such as 
	antibody CDR loops with redundant numbering). This function checks whether 
	an atom table made by tabulate_pdb_atom_lines is missing residues or has 
	insertions. Residues with lettered names (which don't convert to integers) 
	are identified as insertions. Deletions are identified by finding gaps in a 
	range, which by default goes from 1 to the max residue number of each chain, 
	though the bounds can be set manually (min_res, max_res) or automatically 
	identify the range of the chain (by setting the value to 0). Returns a dict 
	of dicts. Outer: insertions, deletions; inner: a list for each chain.
	"""
	# Extract CA-only table to read sequence
	ca_table = atom_table[atom_table['atom_name'] == 'CA']

	# Initialize report dict
	residue_indels = {i:{} for i in ['insertions', 'deletions']}

	# Iterate through all chains to collect indels
	for chain in ca_table['chain_id'].unique():
		# Isolate single chain
		chain_ca_table = ca_table[ca_table['chain_id'] == chain]

		# List all residues
		res_list = [str2int(i) for i in chain_ca_table['res_number']]

		# Identify insertions
		insertion_residues = [i for i in res_list if type(i) != int]
		residue_indels['insertions'][chain] = insertion_residues

		# Finding missing residues
		res_list = [res for res in res_list if res not in insertion_residues]
		## Determine chain min residue
		chain_min = min_res
		if min_res == 0:
			chain_min =  min(res_list)
		## Determine chain max residue
		chain_max = max_res
		if max_res == 0:
			chain_max =  max(res_list)
		## Check for gaps in residue number list
		missing_res = [res for res in range(chain_min, chain_max + 1) 
			if res not in res_list]
		residue_indels['deletions'][chain] = missing_res

	return residue_indels


def atom_table_to_pdb(atom_table, pdb_name):
	"""
	Does the reverse operation of tabulate_pdb_atom_lines, converting a PDB atom
	table back into a PDB with a specified pdb_name.
	"""
	# Create PDB line template string
	pdb_line_string = '{:<6}{:>5} {:^4}{:<1}{:<3} {:<1}{:^5}    '
	pdb_line_string += '{:<8}{:<8}{:<8}{:^6}{:^6}      {:<4}{:<4}\n'

	# Write formatted lines to the PDB file
	with open(pdb_name, 'w') as w:
		for ind, row in atom_table.iterrows():
			w.write(pdb_line_string.format(*[str(i) for i in list(row)]))

	return


def extract_pdb_energy_lines(pdb):
	"""
	Finds and returns the lines from a PDB that include the pose energies	
	"""
	# Read the PDB
	with open(pdb, 'r') as r:
		pdb_lines = r.readlines()

	# Identify endpoints of pose energies table
	e_table_begin = None
	e_table_end = None
	for n, pdb_line in enumerate(pdb_lines):
		if "BEGIN_POSE_ENERGIES_TABLE" in pdb_line:
			e_table_begin = n + 1
		if "END_POSE_ENERGIES_TABLE" in pdb_line:
			e_table_end = n
			break

	return pdb_lines[e_table_begin: e_table_end]


def tabulate_pdb_energy_lines(pdb):
	"""
	Generates a pandas dataframe from a PDB's Rosetta energy lines.
	"""
	import pandas as pd
	import re

	# Extract PDB Rosetta energy lines
	energy_lines = extract_pdb_energy_lines(pdb)

	# Create table
	headers = energy_lines.pop(0).strip().split()
	energy_table = pd.DataFrame(columns=headers)

	# Populate the table converting line strings to series of floats
	for eline in energy_lines:
		line_energies = [str2float(i) for i in eline.strip().split()]
		line_energies = pd. Series(line_energies, index=headers)
		energy_table = energy_table.append(line_energies, ignore_index=True)
    
	# Create residue site and name columns from label
	energy_table['pose_number'] = energy_table.apply(
		lambda row: str2int(re.split('\W+|_', row['label'])[-1]), 
		axis='columns')
	energy_table['residue'] = energy_table.apply(
		lambda row: convert_aa_name(re.split('\W+|_', row['label'])[0], 
		return_orig=True), axis='columns')
    
	# Reorder columns
	cols = ['pose_number', 'residue', 'total']
	headers.remove('label')
	headers.remove('total')
	cols += headers
	energy_table = energy_table[cols]

	return energy_table

################################################################################
# Pose setup functions (functions require PyRosetta)

def pyrosetta_init(verbose=False, preserve_header=False, no_link=False, sugars=False, 
	ligands=None, extra_opts=None, init_pyrosetta=True):
	""" 
	Initializes PyRosetta with a set of init options. Returns the options list.

	Options:
		verbose (default=False) will mute all Rosetta output if False
		preserve_header (default=False) will preserve PDB headers if True
		sugars (default=False) will add a number of flags recommended by Labonte
		no_link (default=False) will prevent adding LINK lines to output PDBs
		ligands (default=None) will add a single string or list of extra_res_fa 
			params files 
		extra_opts (default=None) will add a list of other arguments given as 
			strings. Do not include dashes; they will be added automatically.
		init (default=True) will initialize PyRosetta with the given options.
	"""
	from pyrosetta import init

	# Initialize options list
	ros_opts = []

	# Add options
	if True: # I don't know when we wouldn't want this
		ros_opts.append('flip_HNQ')
	if not verbose:
		ros_opts.append('mute all')
	if preserve_header:
		ros_opts.append('run:preserve_header')
	if no_link:
		ros_opts.append('write_pdb_link_records false')
	if sugars:
		ros_opts += ['include_sugars', 'auto_detect_glycan_connections',
			'maintain_links', 'alternate_3_letter_codes glycam', 
			'write_glycan_pdb_codes', 'ignore_zero_occupancy false',
			'load_PDB_components false', 'no_fconfig']
	if isinstance(ligands, list):
		for l in ligands:
			ros_opts.append('extra_res_fa {}'.format(l))
	if isinstance(ligands, str):
		ros_opts.append('extra_res_fa {}'.format(ligands))
	if extra_opts:
		for i in extra_opts:
			ros_opts.append(i)

	# Initialize PyRosetta
	if init_pyrosetta:
		init(options=' '.join(['-{}'.format(i) for i in ros_opts]))

	return ros_opts


def apply_symmetry(pose, symfile):
	""" Set up a pose for symmetric sampling/scoring """
	from pyrosetta.rosetta.protocols.symmetry import SetupForSymmetryMover

	sfsm = SetupForSymmetryMover(symfile)
	sfsm.apply(pose)

	return pose


def apply_membrane(pose, membfile, symmetric=False):
	""" Applies AddMembraneMover to a pose """
	from pyrosetta.rosetta.protocols.membrane import AddMembraneMover
	from pyrosetta.rosetta.protocols.membrane.symmetry import \
		SymmetricAddMembraneMover

	if symmetric:
		add_memb = SymmetricAddMembraneMover(membfile)
		add_memb.apply(pose)
	else:
		add_memb = AddMembraneMover(membfile)
		add_memb.apply(pose)

	return pose


def load_pose(pdb, path=None, enzdes_cst=None, coord_cst=False, res_type_cst=0, 
	symmetry=None, membrane=None):
	"""
	Loads a PDB or PDB.GZ file as a pose. If the pdb argument includes the path,
	no path argument is necessary. If a pdb basename and path argument are 
	given, will attempt to load the pdb from the specified path. Accepts 
	arguments to apply enzdes constraints, full-pose CA coordinate constraints, 
	residue type constraints of a given weight, symmetry, or membrane.
	"""
	from os.path import join
	from pyrosetta import pose_from_file

	# Get PDB name with path, correcting for zipped/unzipped extension
	pdb_name = pdb
	if path:
		pdb_name = join(path, pdb)
	pdb_name = find_maybe_compressed_file(pdb_name)

	# Load pose
	pose = pose_from_file(pdb_name)

	# Applying enzdes constraints
	if enzdes_cst:
		pose = apply_enzdes_constraints(pose, enzdes_cst)

	# Applying coordinate constraints
	if coord_cst:
		pose = apply_coord_constraints(pose)

	# Applying residue type constraints
	if res_type_cst:
		pose = apply_res_type_constraints(pose, penalty=res_type_cst)
	
	# Applying symmetry
	if symmetry: 
		pose = apply_symmetry(pose, symmetry)
			
	# Set up membrane
	if membrane:
		pose = apply_membrane(pose, membrane, symmetric=symmetry)
	
	return pose


def pose_copy(pose):
	""" Returns a copy of a pose """
	import pyrosetta as pr

	copied_pose = pr.Pose()
	copied_pose.assign(pose)

	return copied_pose

################################################################################
# Pose informatics functions (functions require PyRosetta)

def pose2pdb(pose, residue, include_chain=True):
	"""
	Given a pose and a an integer representing a residue in the pose, returns 
	the PDB-numbered residue. Rosetta stores residues as a contiguous list of 
	integers from 1 to the total number, whereas PDBs might not start at 1, or
	might have gaps, different chains, etc. 

	If include_chain is True, returns a list where the first element is the 
	PDB residue number and the second is the chain.If include_chain is False,
	only the integer residue number will be returned.
	"""
	# Get PDB info as a string
	pdb_res_string =  pose.pdb_info().pose2pdb(residue)

	# Convert residue number into an integer
	pdb_res_list = [str2int(i) for i in pdb_res_string.split()]

	if include_chain:
		return pdb_res_list
	else:
		return pdb_res_list[0]


def pdb2pose(pose, residue, chain='A'):
	"""
	Given a pose and a an integer representing a residue in the pose, returns 
	the pose-numbered residue. Rosetta stores residues as a contiguous list of 
	integers from 1 to the total number, whereas PDBs might not start at 1, or
	might have gaps, different chains, etc. 

	By default, this function assumes that the residue is in chain A, but it is 
	a good idea to explicily include the chain letter as an argument.

	Returns an integer pose residue number.
	"""
	return pose.pdb_info().pdb2pose(chain, residue)	


def get_pose_chain_list(pose):
	"""
	Get a list of chain names in a pose
	"""
	pose_chains = []
	for chain in range(1, pose.num_chains() + 1):
		pose_chains.append(pose.pdb_info().chain(pose.chain_begin(chain)))

	return pose_chains


def get_pose_sequence(pose, selection=None):
	""" 
	Determine the sequence of a pose. Providing a selector will return only the 
	sequence of the selection.
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import SequenceMetric

	# Create sequence metric
	seqm = SequenceMetric()

	# Add the selector
	if selection:
		seqm.set_residue_selector(selection)

	return seqm.calculate(pose)


def find_res_aa(pose, residue, name_length=1):
	"""
	Find what AA is in a given pose position. By default, gives the 1-letter
	name. Can give the 3-letter instead. name_length must be either 1 or 3.
	"""
	if name_length not in [1, 3]:
		raise ValueError('Amino acid name length must be either 1 or 3.')

	if name_length == 1:
		return pose.residue(residue).name1()
	else:
		return pose.residue(residue).name3()


def find_res_atom(pose, resnum, atom_type='CA'):
	""" 
	For a given pose and residue number, returns the a specified Atom object 
	"""
	return pose.residue(resnum).atom(atom_type)


def find_res_atom_index(pose, resnum, atom_type='CA'):
	""" 
	For a given pose and residue number, returns the index of a specified atom 
	"""
	return pose.residue(resnum).atom_index(atom_type)


def find_atom_id(pose, resnum, atom_type='CA'):
	""" 
	For a given pose and residue number, returns an AtomID for a specified atom.
	AtomID takes an atom index within a residue and a residue number in a pose. 
	"""
	from pyrosetta import AtomID

	return AtomID(pose.residue(resnum).atom_index(atom_type), resnum)


def find_dihedral_atom_ids(pose, resnum, dihedral):
	"""
	For a given pose, residue number, and dehedral, returns a list of four 
	AtomID objects corresponding to the atoms comprising that dihedral.

	Options are phi, psi, and omega
	"""
	# Confirm acceptable angle selection
	assert dihedral in ['phi', 'psi', 'omega']

	# Populate list of relevant backbone atoms near dihedrals
	bb_atomids = []
	for atom in ['C']:
		bb_atomids.append(find_atom_id(pose, resnum - 1, atom))
	for atom in ['N', 'CA', 'C']:
		bb_atomids.append(find_atom_id(pose, resnum, atom))
	for atom in ['N', 'CA']:
		bb_atomids.append(find_atom_id(pose, resnum + 1, atom))

	# Phi angle
	if dihedral == 'phi':
		return bb_atomids[:-2]

	# Psi angle
	if dihedral == 'psi':
		return bb_atomids[1:-1]

	# Omega angle
	if dihedral == 'omega':
		return bb_atomids[2:]


def find_atom_coords(pose, resnum, atom_type='CA'):
	""" 
	For a given pose and residue number, returns the coordinates of a 
	specified atom type 
	"""
	return pose.residue(resnum).atom(atom_type).xyz()


def list_pose_coords(pose, atom_type='CA'):
	""" 
	For a given pose, list all coordinates of a given atom type, CA by default
	"""
	# Initialize list of CA coordinates
	coords = []

	# Populating list of CA coordinates 
	for res in range(1, pose.total_residue() + 1):
		res_ca = find_atom_coords(pose, res, atom_type=atom_type)
		coords.append(res_ca)

	return coords


def get_b_factor(pose, residue):
	""" 
	Given a pose and a residue number, will return the average b-factor of the 
	backbone atoms (N, CA, C) for the specified residue. Requires residue to  
	be input as a pose number, as opposed to a PDB number. 
	"""
	bfactor = pose.pdb_info().bfactor
	atom_index = pose.residue(residue).atom_index

	total_b = 0.0
	for atom in ['N', 'CA', 'C']:
		total_b += bfactor(residue, atom_index(atom))

	# Return average for three atoms
	return total_b / 3


def tabulate_pose_residues(pose, ss=False, dihedrals=False, b_factor=False,
	res_name=1):
	"""
	For a given pose, makes a pandas DataFrame listing all residues' chain, 
	PDB number, pose chain, pose number, amino acid, and optioally secondary 
	structure classification, dihedral angles, and/or B-factor.

	By default, residue names will be single-letter (res_name=1, ex: P), but 
	res_name can be 0 for full name (ex: PRO:NtermProteinFull) or 3-letter name
	(ex: PRO). Bad inputs will result in single-letter names as per default.
	"""
	import pandas as pd
	if ss:
		from pyrosetta.rosetta.core.simple_metrics.metrics import \
			SecondaryStructureMetric
		secstruct_str = SecondaryStructureMetric().calculate(pose)

	# Collect lists of residue numbers and letters
	pose_dict = {'pdb_chain': [], 'pdb_number': [], 'pose_chain': [], 
		'pose_number': [], 'residue': []}
	if ss:
		pose_dict = {**pose_dict, 'ss': [i for i in secstruct_str]}
	if dihedrals:
		pose_dict = {**pose_dict, 'phi': [], 'psi': []}
	if b_factor:
		pose_dict = {**pose_dict, 'b_factor': []}

	for res in range(1, pose.total_residue() + 1):
		# PDB and Pose residue identification
		res_pbd_no_chain = pose2pdb(pose, res)
		pose_dict['pdb_chain'].append(res_pbd_no_chain[1])
		pose_dict['pdb_number'].append(res_pbd_no_chain[0])
		pose_dict['pose_chain'].append(pose.chain(res))
		pose_dict['pose_number'].append(res)
		# Residue name
		if res_name == 0:
			pose_dict['residue'].append(find_res_aa(pose, res, 3))
		elif res_name == 3:
			pose_dict['residue'].append(find_res_aa(pose, res, 3))
		else:
			pose_dict['residue'].append(find_res_aa(pose, res, 1))
		# Extra info
		if dihedrals:
			pose_dict['phi'].append(pose.phi(res))
			pose_dict['psi'].append(pose.psi(res))
		if b_factor:
			pose_dict['b_factor'].append(get_b_factor(pose, res))

	# Create a dataframe from listed residues
	return pd.DataFrame(pose_dict)


def select_row_block(df, target_parameter, target_value, contiguity_parameter):
    """
    Extracts a contiguous block of rows from a dataframe around a target. For 
    example, using a tabulated pose from tabulate_pose_residues to extract all 
    residues in a secondary structure element based on a single residue in that
    element can be done with the following command:

    select_row_block(pose_table, 'pdb_number', 78, 'ss')

    Where pose_table is the dataframe from tabulate_pose_residues (with ss), 
	and we are extracting the whole loop that includes residue 78.
    """
    # Reset row indices to congituous integers
    df = df.reset_index(drop=True)
    
    # Determine target row index
    target_row = list(df.index[df[target_parameter] == target_value])[0]
    
    # Determine value of target row in the contiguity parameter column
    contiguity_value = df.iloc[target_row][contiguity_parameter]
    
    # Determine indices of rows not matching contiguity value
    noncontiguous_indices = list(
    	df.index[df[contiguity_parameter] != contiguity_value])
    
    # Determine position of bounds of contiguous block around target in 
    # the noncontiguous_indices list
    i_lower = find_nearest_in_array(
    	noncontiguous_indices, target_row, lesser=True)
    i_upper = find_nearest_in_array(
    	noncontiguous_indices, target_row, greater=True)
    
    # Determine bounds of contiguous block around target, correcting for edge cases
    if i_lower == None: 
        lower_bound = -1
    else: 
        lower_bound = noncontiguous_indices[i_lower]
        
    if i_upper == None:
        upper_bound = len(df) + 1
    else:
        upper_bound = noncontiguous_indices[i_upper]
    
    # Extract the portion of the dataframe with indices between the bounds
    return df[(df.index > lower_bound) & (df.index < upper_bound)]


def find_sequence_in_pose_table(pose_table, sequence, instances=0):
	"""
	Given a pose table generated by tabulate_pose_residues and a sequence, 
	extracts the portion(s) of the table that include(s) the given sequence.
	Sequence must be an exact match, otherwise there will be an error. If 
	multiple instances of the sequence exist, it is possible to specify which 
	instance will be returned, though by default all instances are included.
	"""
	# Get initial list of possible sites for sequence, matching the first letter
	# Exclude sites that would run off the end of the table
	possible_sites = list(
		pose_table[pose_table['residue'] == sequence[0]].index)
	possible_sites = [i for i in possible_sites 
		if (i+len(sequence)) <= max(pose_table.index)]

	# Iterate through the sequence, at each site narrowing the possible sites
	# list if the tabulated sequence doesn't match the target
	for ind, aa in enumerate(sequence):
		refined_sites = []
		for site in possible_sites:
			if pose_table.loc[site + ind]['residue'] == aa:
				refined_sites.append(site)
		possible_sites = refined_sites
    
    # Raise error if the sequence is not found
	if len(possible_sites) == 0:
		raise ValueError(
			'No instance of the target sequence, {}, was found.'.format(
			sequence))

	# Get lists of rows to collect for each instance of the sequence
	collectable_indices = \
		[list(range(i, i+len(sequence))) for i in possible_sites]

	# Determine which to return
	if instances == 0:
		selected_rows = flatten_nested_lists(collectable_indices)
	else:
		selected_rows = collectable_indices[instances - 1]

	return pose_table.iloc[selected_rows]


def set_pose_name(pose, pose_name):
	"""
	Set the name of a pose in the PDB info to an input string. Necessary for 
	outputting multiple poses as silent files. Names are by default the full
	PDB name, including path, for poses loaded from files, or the first 8 
	letters of the sequence for poses created from sequences.
	"""
	pose.pdb_info().name(pose_name)

	return pose

################################################################################
# Pose geometric evaluation functions (functions require PyRosetta)

def check_pose_continuity(pose):
	"""
	Scans through all residues in a pose, checking CA and N coordinates, and 
	identifies chain breaks by distances deviating more than 10% from the ideal 
	1.33 A. (This is how the ChainBreakFilter worked.) Returns a bool indicating 
	if loop is continuous (so True means no breaks were found), a list of 
	C-N distances, and a list of pose numbers at which breaks were found. 
	"""
	# Get lists of N and C residues
	n_coords = list_pose_coords(pose, atom_type='N')
	c_coords = list_pose_coords(pose, atom_type='C')

	# Check C-N diatances
	continuous = True
	c_n_distances = []
	break_sites = []
	for i in range(len(n_coords) - 1):
		distance = calc_distance(c_coords[i], n_coords[i+1])
		c_n_distances.append(distance)

	# Check whether distance indicates a chain break
		if not 0.9 * 1.33 <= distance <= 1.1 * 1.33:
			continuous = False 
			break_sites.append(i)

	return continuous, c_n_distances, break_sites


def identify_res_layer(pose, res_number, target_chain=None):
	"""
	Determines whether a given residue in a pose is in the core, boundary, or 
	surface layer of the protein. If no target chain is given, calculates layer 
	in the context of the whole pose. If a target chain is given, layer will be 
	determined in the context of only that chain.
	"""
	from pyrosetta import Pose
	from pyrosetta.rosetta.core.select.residue_selector import LayerSelector

	# If the pose has multiple chains and one is desired, isolate it
	if target_chain:
		check_pose = Pose(pose, pose.chain_begin(target_chain), 
            pose.chain_end(target_chain))
	else:
		check_pose = pose
	
	# Identify layer with LayerSelector
	layer_selector = LayerSelector()

	# Checking core
	layer_selector.set_layers(1, 0, 0)
	core_selection = layer_selector.apply(pose)
	if core_selection[res_number]:
		return 'CORE'

	# Checking boundary
	layer_selector.set_layers(0, 1, 0)
	boundary_selection = layer_selector.apply(pose)
	if boundary_selection[res_number]:
		return 'BOUNDARY'

	# Checking surface
	layer_selector.set_layers(0, 0, 1)
	surface_selection = layer_selector.apply(pose)
	if surface_selection[res_number]:
		return 'SURFACE'


def rmsd_type(r_type='bb_ca'):
	"""
	By default, RMSDs are calculated for backbone CAs. This function allows
	for selection of alternative RMSD methods.

	Options:
		'bb_ca' 		# Default
		'bb_heavy'
		'bb'
		'sc_heavy'
		'sc'
		'all_heavy'
		'all'
	"""
	from pyrosetta.rosetta.core.scoring import rmsd_atoms

	# Check correct input
	rmsd_type_options = ['bb_ca', 'bb_heavy', 'bb', 'sc_heavy', 'sc', 
		'all_heavy', 'all', None]
	if r_type not in rmsd_type_options:
		print("You have entered an invalid RMSD type. Select from:")
		for rt in rmsd_type_options[:-1]:
			print('\t--', rt)
		raise ValueError('Invalid RMSD type')

	# Convert None to default
	if r_type == None:
		r_type = 'bb_ca'

	# Get RMSD type
	rmsd_types = {
		'bb_ca': rmsd_atoms.rmsd_protein_bb_ca,
		'bb_heavy': rmsd_atoms.rmsd_protein_bb_heavy,
		'bb': rmsd_atoms.rmsd_protein_bb_heavy_including_O,
		'sc_heavy': rmsd_atoms.rmsd_sc_heavy,
		'sc': rmsd_atoms.rmsd_sc,
		'all_heavy': rmsd_atoms.rmsd_all_heavy,
		'all': rmsd_atoms.rmsd_all
		}
	return rmsd_types['bb_ca']


def rmsd_metric(ref_pose, ref_calc_selection=None, target_calc_selection=None, 
	ref_align_selection=None, target_align_selection=None, r_type=None):
	"""
	Creates an RMSD metric based on a reference pose. 

	Selectors can be provided to align and/or calculate RMSDs based on subsets 
	of the pose. By default, the calculation will align and evaluate based on 
	the whole pose (poses must be the same number of residues). Giving selectors 
	for ref and target calc_selection will result in the RMSD being calculated 
	only for selected residues. Giving selectors for ref and target 
	align_selection will result in the poses being aligned based on only 
	selected residues. Selections must be given in pairs, and selections for ref 
	and target must include the same number of residues in each selection 
	category. If calculation selections are given without alignment selections, 
	alignment will use the calculation selections.

	r_type sets the RMSD calculation type. Options are:
		'bb_ca'		# Default
		'bb_heavy'
		'bb'
		'sc_heavy'
		'sc'
		'all_heavy'
		'all'
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import RMSDMetric

	# Confirming paired selector arguments
	if not any([
		ref_calc_selection == None and target_calc_selection == None,
		ref_calc_selection != None and target_calc_selection != None]):
		raise ValueError("""Reference and taget calculation selections must be 
			submitted together.""")
	if not any([
		ref_align_selection == None and target_align_selection == None,
		ref_align_selection != None and target_align_selection != None]):
		raise ValueError("""Reference and taget alignment selections must be 
			submitted together.""")

	# Set selector defaults
	if ref_calc_selection == None:
		ref_calc_selection = full_selector()
	if target_calc_selection == None:
		target_calc_selection = full_selector()
	if ref_align_selection == None:
		ref_align_selection = ref_calc_selection
	if target_align_selection == None:
		target_align_selection = target_calc_selection

	# Create the RMSDMetric with reference pose
	rmsd_metric = RMSDMetric()
	rmsd_metric.set_comparison_pose(ref_pose)
	rmsd_metric.set_rmsd_type(rmsd_type(r_type))
	rmsd_metric.set_run_superimpose(True)
	rmsd_metric.set_residue_selector_reference(ref_calc_selection)
	rmsd_metric.set_residue_selector(target_calc_selection)
	rmsd_metric.set_residue_selector_super_reference(ref_align_selection)
	rmsd_metric.set_residue_selector_super(target_align_selection)

	return rmsd_metric


def get_rmsd(ref_pose, pose, 
	ref_calc_selection=None, target_calc_selection=None, 
	ref_align_selection=None, target_align_selection=None, r_type=None):
	"""
	Given two poses of equal size, determines RMSD. The first pose is the 
	one to which the second is compared. 

	Selectors can be provided to align and/or calculate RMSDs based on subsets 
	of the pose. By default, the calculation will align and evaluate based on 
	the whole pose (poses must be the same number of residues). Giving selectors 
	for ref and target calc_selection will result in the RMSD being calculated 
	only for selected residues. Giving selectors for ref and target 
	align_selection will result in the poses being aligned based on only 
	selected residues. Selections must be given in pairs, and selections for ref 
	and target must include the same number of residues in each selection 
	category. If calculation selections are given without alignment selections, 
	alignment will use the calculation selections.

	r_type sets the RMSD calculation type. Options are:
		'bb_ca'		# Default
		'bb_heavy'
		'bb'
		'sc_heavy'
		'sc'
		'all_heavy'
		'all'
	"""
	# Create the RMSDMetric, setting pose_1 as the reference
	rmet = rmsd_metric(ref_pose, ref_calc_selection, target_calc_selection, 
	ref_align_selection, target_align_selection, r_type)

	# Use the RMSDMetirc to calculate the RMSD of pose_2
	rmsd = rmet.calculate(pose)
	
	return rmsd


def check_selection_proximity(pose, selection_1, selection_2):
	"""
	Determines whether any residues in one selector are close enough to 
	potentially interact with residues from a second selector, 
	using an InterGroupInterfaceByVector selector with default settings.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		InterGroupInterfaceByVectorSelector, NotResidueSelector, \
		TrueResidueSelector

	# Make full-pose selection
	full_pose = TrueResidueSelector()
	
	# Make selection for the full pose minus the first selector
	not_selection_1 = NotResidueSelector(selection_1)
	full_minus_1 = selector_intersection(full_pose, not_selection_1)
	
	# Make selection for interacting residues between selection 1 the rest of the pose
	igibv = InterGroupInterfaceByVectorSelector()
	igibv.group1_selector(selection_1)
	igibv.group2_selector(full_minus_1)
	
	# Find intersection of selector_1's interaction partners and selector_2
	selection_overlap = selector_intersection(igibv, selection_2)
	
	# Check if there are residues in the intersection, or if it is empty
	# If it is empty, the Boolean will be False. Otherwise, it will be True
	selections_do_overlap = bool(selector_to_list(pose, selection_overlap))

	return selections_do_overlap


def check_coevolution(pose, substitutions, score_function=None):
	"""
	Given a pose and and a list of substitution sites, makes selectors for the 
	substitution sites and checkes whether the selections interact. If a score
	function is given, interaction is defined by having a nonzero interface 
	energy. If no score function is given, interaction is defined as having CA
	within 5.5A or within 11A if the CBs are oriented toward each other.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		ResidueIndexSelector

	# Set output to False unless an interaction is found.
	sites_interact = False

	# Automatically no interaction if there are not multiple substitutions
	if len(substitutions) < 2:
		return sites_interact

	# Non-redundantly iterate pairwise through the list of substitutions 
	# Skip last res to avoid self-comparison
	for n, sub1 in enumerate(substitutions[:-2]):
		# Make selector for first residue 
		res1 = ResidueIndexSelector(str(sub1))

		# Iterate through all subsequent substitution sites
		for sub2 in substitutions[n + 1:]:
			# Make selector for second residue 
			res2 = ResidueIndexSelector(str(sub2))

			# Checking interaction by energy
			if score_function:
				# Determine interface energy
				intE = interaction_energy(pose, score_function, res1, res2)

				# If the energy is nonzero, residues are interacting
				if intE != 0:
					sites_interact = True
					break 

			# Checking interaction by geometry
			else:
				# Calculating proximity
				selections_nearby = check_selection_proximity(pose, res1, res2)

				# If selections are nearby, residues are interacting
				if selections_nearby:
					sites_interact = True
					break 

	# When either an interaction is found or when iteration completes, return
	# whether sites interact
	return sites_interact


def sasa_metric(pose, selection=None, sasa_mode='all_sasa', apply_sm=False):
	"""
	Calculates solvent-accessible surface area for a pose or a selected part of 
	a pose. Can calculate for all residues, or restrict to just polars or just
	hydrophobics. Mode must be either all_sasa, polar_sasa, or hydrophobic_sasa.

	If apply_sm is True, the SimpleMetric calculation will be added to the 
	pose energies list and output by the job distributor 
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import SasaMetric 

	# Confirm acceptable mode selection
	if sasa_mode not in ['all_sasa', 'polar_sasa', 'hydrophobic_sasa']:
		raise ValueError(
			"sasa_mode must be 'all_sasa', 'polar_sasa', or 'hydrophobic_sasa'")

	# Create the simple metric
	sasa = SasaMetric()
	sasa.set_sasa_metric_mode('all_sasa')

	# Adjust for residue selection
	if selection:
		sasa.set_residue_selector(selection)

	# Apply to the pose
	if apply_sm:
		sasa.apply(pose)

	return sasa.calculate(pose)

################################################################################
# Selectors (functions require PyRosetta)

def empty_selector():
	"""
	Creates an empty residue selector
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		FalseResidueSelector

	return FalseResidueSelector()


def full_selector():
	"""
	Creates a selection comprising the entire pose
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		TrueResidueSelector

	return TrueResidueSelector()


def chain_selector(chain):
	"""
	Creates a chain selector for a given chain, either letter or number.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import ChainSelector

	return ChainSelector(chain)


def index_selector(indices):
	"""
	Creates an index selector for a given selection. If a string is given, 
	uses that string directly in the selector. Converts integers to strings for 
	selector input.	Converts ranges or lists of integers to comma-separated 
	strings for selector input.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		ResidueIndexSelector

	if isinstance(indices, str):
		return ResidueIndexSelector(indices)

	if isinstance(indices, int):
		return ResidueIndexSelector(str(indices))

	if type(indices) in [list, range]:
		ind_str = join_list(indices, ',')
		return ResidueIndexSelector(ind_str)


def upstream_selector(jump=1):
	"""
	Selects all residues upstream of a given jump (default = 1)
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		JumpUpstreamSelector

	return JumpUpstreamSelector(jump)


def downstream_selector(jump=1):
	"""
	Selects all residues downstream of a given jump (default = 1)
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		JumpDownstreamSelector

	return JumpDownstreamSelector(jump)


def close_selector(focus, threshold=5.5):
	"""
	Creates a CloseContactResidueSelector, selecting residues with atoms close
	to a focus selection. Close is defined as within a set distance in 
	Angstroms (default=4.5).
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		CloseContactResidueSelector

	ccrs = CloseContactResidueSelector()
	ccrs.central_residue_group_selector(focus)
	ccrs.threshold(threshold)

	return ccrs


def one_side_close_selector(included_side, excluded_side, threshold=5.5):
	"""
	CloseContactResidueSelector selects the interfacial residues 
	between a pair of selections, including residues from both sides. This 
	function changes the behavior, selecting only the residues on the 
	included_side of the interface between two selections.
	"""
	# Create interface selection
	close_residues = close_selector(included_side, threshold=threshold)

	# Exclude residues on the excluded_side
	return selector_intersection(included_side, close_residues)


def close_with_selection_selector(selection, threshold=5.5):
	"""
	Similar to a neighbor_selector with include_focus=False, but using
	an CloseContactResidueSelector instead of a 
	NeighborhoodResidueSelector. 
	"""
	return one_side_close_selector(not_selector(selection),selection,  
		threshold=threshold)
	

def intergroup_selector(selector_1, selector_2, 
	nearby_atom=5.5, cb_dist=11.0, vector_angle=75.0, vector_dist=9.0):
	"""
	Creates an InterGroupInterfaceByVectorSelector from two other selectors.

	Defaults:
		nearby_atom		 5.5
		cb_dist			11.0
		vector_angle	75.0
		vector_dist		 9.0

	Turning nearby_atom to 0 results in selection by sidechain orientation only.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		InterGroupInterfaceByVectorSelector

	# Create selector
	inter_selector = InterGroupInterfaceByVectorSelector()

	# Add selections to check interface
	inter_selector.group1_selector(selector_1)
	inter_selector.group2_selector(selector_2)

	# Set interface detection parameters
	inter_selector.nearby_atom_cut(nearby_atom)
	inter_selector.cb_dist_cut(cb_dist)
	inter_selector.vector_angle_cut(vector_angle)
	inter_selector.vector_dist_cut(vector_dist)

	return inter_selector


def one_side_interface_selector(included_side, excluded_side, 
	nearby_atom=5.5, cb_dist=11.0, vector_angle=75.0, vector_dist=9.0):
	"""
	InterGroupInterfaceByVectorSelector selects the interfacial residues 
	between a pair of selections, including residues from both sides. This 
	function changes the behavior, selecting only the residues on the 
	included_side of the interface between two selections.
	"""
	# Create interface selection
	interface_residues = intergroup_selector(included_side, excluded_side,
		nearby_atom=nearby_atom, cb_dist=cb_dist, vector_angle=vector_angle, 
		vector_dist=vector_dist)

	# Exclude residues on the excluded_side
	return selector_intersection(included_side, interface_residues)


def interface_with_selection_selector(selection, 
	nearby_atom=5.5, cb_dist=11.0, vector_angle=75.0, vector_dist=9.0):
	"""
	Similar to a neighbor_selector with include_focus=False, but using
	an InterGroupInterfaceByVectorSelector instead of a 
	NeighborhoodResidueSelector. 
	"""
	return one_side_interface_selector(not_selector(selection), selection, 
		nearby_atom=nearby_atom, cb_dist=cb_dist, vector_angle=vector_angle, 
		vector_dist=vector_dist)


def close_and_interface_selector(selector_1, selector_2,  
	nearby_atom=5.5, cb_dist=11.0, vector_angle=75.0, vector_dist=9.0):
	"""
	Creates an interfacial selection, combining both CloseContactResidueSelector
	to detect touching residues and InterGroupInterfaceByVectorSelector to 
	detect residues with the design potential to touch.

	Defaults:
		nearby_atom				 5.5 		Used for both selectors
		cb_dist					11.0
		vector_angle			75.0
		vector_dist				 9.0
	"""
	# Create CloseContactResidueSelector
	close_selector_1 = close_selector(selector_1, threshold=nearby_atom)
	close_selector_2 = close_selector(selector_2, threshold=nearby_atom)
	close = selector_intersection(close_selector_1, close_selector_2)

	# Create InterGroupInterfaceByVectorSelector
	intergroup = intergroup_selector(selector_1, selector_2,
		nearby_atom=nearby_atom, cb_dist=cb_dist, vector_angle=vector_angle, 
		vector_dist=vector_dist)

	return selector_union(close, intergroup)


def one_side_close_and_interface_selector(included_side, excluded_side, 
	nearby_atom=5.5, cb_dist=11.0, vector_angle=75.0, vector_dist=9.0):
	"""
	close_and_interface_selector selects the interfacial residues between a 
	pair of selections, including residues from both sides. This function 
	changes the behavior, selecting only the residues on the included_side 
	of the interface between two selections.
	"""
	# Create interface selection
	interface_residues = close_and_interface_selector(included_side, 
		excluded_side, nearby_atom=nearby_atom, cb_dist=cb_dist, 
		vector_angle=vector_angle, vector_dist=vector_dist)

	# Exclude residues on the excluded_side
	return selector_intersection(included_side, interface_residues)


def close_interface_with_selection_selector(selection, nearby_atom=5.5, 
	cb_dist=11.0, vector_angle=75.0, vector_dist=9.0):
	"""
	Similar to a neighbor_selector with include_focus=False, but using
	a close_and_interface_selector instead of a NeighborhoodResidueSelector. 
	"""
	return one_side_close_and_interface_selector(not_selector(selection), 
		selection, nearby_atom=nearby_atom, cb_dist=cb_dist, 
		vector_angle=vector_angle, vector_dist=vector_dist)


def neighbor_selector(selection, include_focus=False, distance=8):
	"""
	Creates a NeighborhoodResidueSelector from a given selection. Can adjust 
	whether the input selection is included in the output selector with the 
	include_focus option (excluded by default). Can adjust CA distance threshold
	with the distance option (default 8A).
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		NeighborhoodResidueSelector

	neighbor_selection = NeighborhoodResidueSelector()
	neighbor_selection.set_focus_selector(selection)
	neighbor_selection.set_include_focus_in_subset(include_focus)
	neighbor_selection.set_distance(distance)

	return neighbor_selection


def secstruct_selector(ss, minE=3, minH=4):
	"""
	Creates a SecondaryStructureSelector with adjusted defaults for minimal 
	qualifying element length for sheets and helices. ss should be a string,
	'E', 'H', or 'L', or a combination thereof ex ('HL'). 

	Defaults of the function differ from the SecondaryStructureSelector 
	default lengths for counting sheets and helices. Single-residue elements 
	don't count. Sheets must be at least three residues long to form the proper 
	H-bonds, and helices must be at least 4.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		SecondaryStructureSelector

	# Check correct input
	ss = ss.upper()
	for ss_type in ss:
		if ss_type not in ['E', 'H', 'L']:
			raise ValueError('{} is not a secondary structure. Secondary \
				structure options are E, H, and L.'.format(ss_type).replace(
				'\t', ''))

	# Create selector
	sss = SecondaryStructureSelector()
	sss.set_selected_ss(ss)
	sss.set_minE(minE)
	sss.set_minH(minH)

	return sss


def layer_selector(layer):
	""" 
	Creates a layer selector, based on a string input. Layers are:
	S: surface
	B: boundary
	C: core
	Inputting a string including one letter will select that layer. Inputting a 
	string with all three will select the whole pose. Inputting an empty string, 
	or one with only characters other than B, C, and S (case insensitive) will 
	select nothing
	"""
	from pyrosetta.rosetta.core.select.residue_selector import LayerSelector

	# Capitalize input string
	layer = layer.upper()

	# Create selector
	layr_selector = LayerSelector()

	# Determine layer(s) to select
	select_core = 0
	select_boundary = 0
	select_surface = 0
	if 'C' in layer: select_core = 1
	if 'B' in layer: select_boundary = 1
	if 'S' in layer: select_surface = 1

	# Set layer selection
	layr_selector.set_layers(select_core, select_boundary, select_surface)

	return layr_selector


def hbond_selector(selection, include_sc=True, include_bb_bb=True):
	"""
	Creates a selection of residues that have hydrogen bonds with the input 
	selection. Can be adjusted to include, exclude, or only include 
	backbone-backbone bonds. If both include_bb_bb and include_sc are True,
	all bonding residues will be selected. If only include_sc is true, then
	backbone-backbone-bonding residues will not be selected. If only 
	include_bb_bb is selected, residues making bonds involving sidechains will
	not be selected. If both options are false, no residues will be selected.
	"""
	from pyrosetta.rosetta.protocols.residue_selectors import HBondSelector

	# Initialize selector
	hbs = HBondSelector()
	hbs.set_input_set_selector(selection)

	# Include both
	if include_sc & include_bb_bb:
		return hbs

	# Exclude bb-bb bonding residues
	elif include_sc:
		hbs.set_include_bb_bb(False)
		return hbs

	# Select only bb-bb residues
	elif include_bb_bb:
		# Since selector doesn't allow bb-only, subtract two selectors
		hb_with_bb = HBondSelector()
		hb_with_bb.set_input_set_selector(selection)
		no_sc = not_selector(hbs)
		return selector_intersection(hb_with_bb, no_sc)

	# Empty case
	else:
		return empty_selector()


def not_selector(selection):
	"""
	Generates a NotResidueSelector around a selection, including all residues
	in the pose except those in the input selector.
	"""
	from pyrosetta.rosetta.core.select.residue_selector import \
		NotResidueSelector

	nrs = NotResidueSelector()
	nrs.set_residue_selector(selection)

	return nrs


def selector_intersection(*selectors):
	""" Returns the intersection of any set of selectors """
	from pyrosetta.rosetta.core.select.residue_selector import \
		AndResidueSelector

	intersect_selection = AndResidueSelector()
	for s in selectors:
		intersect_selection.add_residue_selector(s)

	return intersect_selection


def selector_union(*selectors):
	""" Returns the intersection of any set of selectors """
	from pyrosetta.rosetta.core.select.residue_selector import \
	OrResidueSelector

	union_selection = OrResidueSelector()
	for s in selectors:
		union_selection.add_residue_selector(s)

	return union_selection


def selector_to_list(pose, selector, pose_numbering=True):
	""" 
	Converts a selector output vector to a list of selected residues. By 
	default, outputs a list of pose numbers. If pose_numbering is False,
	a list of two-membered lists will be returned, where each element is 
	PDB-numbered residue integer then chain letter. 
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import \
		SelectedResiduesMetric

	# Set up SelectedResiduesMetric
	srm = SelectedResiduesMetric()
	srm.set_residue_selector(selector)
	srm.set_output_in_rosetta_num(pose_numbering)
	
	# Collect selection, and convert to a list
	sel_res_str = srm.calculate(pose)
	if sel_res_str == '':
		return []
	else:
		selected_residues_list = [str2int(i) for i in sel_res_str.split(',')]
		if pose_numbering:
			return selected_residues_list
		else:
			return [split_string_at_numbers(i) for i in selected_residues_list]


def selector_to_pymol(pose, selector, selection_name):
	"""
	Given a pose and a selector, generates a PyMOL selection command on the 
	selection with a given object selection_name
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import \
		SelectedResiduesPyMOLMetric

	# Create selector
	srpmm = SelectedResiduesPyMOLMetric()
	srpmm.set_residue_selector(selector)

	# Generate command
	pymol_command = srpmm.calculate(pose)
	pymol_command = pymol_command.replace('rosetta_sele', selection_name)

	return pymol_command

################################################################################
# Scoring functions (functions require PyRosetta)

def get_sf(rep_type='hard', symmetry=False, membrane=0, constrain=1.0, 
	hbnet=0):
	"""
	Determines the appropriate score function to use, based on a rep_type
	that is either hard (ref2015) or soft (ref2015_soft), whether symmetry 
	and/or membrane modeling are in use, and whether constraints are desired.
	If setting membrane and/or hbnet, change value to desired nonzero weight.
	"""
	from pyrosetta import create_score_function, ScoreFunction
	from pyrosetta.rosetta.core.scoring import ScoreType
	from pyrosetta.rosetta.core.scoring.symmetry import SymmetricScoreFunction

	score_types = {'hard': 'ref2015', 'soft': 'ref2015_soft'}
	assert rep_type in score_types

	# Create base empty score function symmetrically or asymmetrically
	if symmetry: # Declare symmetric score functions
		score_function = SymmetricScoreFunction()
	else:
		score_function = ScoreFunction()

	# Add main score weights
	if rep_type == 'hard':
		score_function.add_weights_from_file('ref2015')
	elif rep_type == 'soft':
		score_function.add_weights_from_file('ref2015_soft')
		if membrane: # Set up a soft-rep version of franklin2019 manually
			score_function.set_weight(ScoreType.fa_water_to_bilayer, membrane)

	# Add membrane weights if appliccable
	if membrane:
		score_function.add_weights_from_file('franklin2019')

	# The score functions do not have constraint weights incorporated in 
	# themselves. If requisite, the constraint weights are added.
	if constrain:
		score_function.set_weight(ScoreType.atom_pair_constraint, constrain)
		score_function.set_weight(ScoreType.coordinate_constraint, constrain)
		score_function.set_weight(ScoreType.angle_constraint, constrain)
		score_function.set_weight(ScoreType.dihedral_constraint, constrain)
		score_function.set_weight(ScoreType.metalbinding_constraint, constrain)
		score_function.set_weight(ScoreType.chainbreak, constrain)
		score_function.set_weight(ScoreType.res_type_constraint, constrain)

	# Optionally adding in hbnet
	if hbnet:
		score_function.set_weight(ScoreType.hbnet, hbnet)
	
	return score_function


def total_energy(pose, score_function, selection=None):
	"""
	Calculates total energy of a pose using a TotalEnergyMetric. If a selector
	is provided, calculates the total energy of the selection rather than the
	whole pose.
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import TotalEnergyMetric

	# Create the metric
	tem = TotalEnergyMetric()
	tem.set_scorefunction(score_function)
	
	# Add the selector
	if selection:
		tem.set_residue_selector(selection)
		
	return tem.calculate(pose)


def calc_single_res_Es(pose, score_function, selection=None):
	"""
	For a given pose and score function, returns a list of single-residue
	energies. Providing a residue selection will limit the per-residue energy 
	calculation to the residues in that selection.
	"""
	from pyrosetta.rosetta.core.simple_metrics.per_residue_metrics import \
	PerResidueEnergyMetric

	prem = PerResidueEnergyMetric()
	prem.set_scorefunction(score_function)
	if selection:
		prem.set_residue_selector(selection)
	
	e_vals = prem.calculate(pose)
	return [energy for res, energy in e_vals.items()]


def interaction_energy(pose, score_function, selection_1, selection_2, 
	apply_sm=False):
	"""
	Given a Rosetta pose, score function, and two residue selectors, 
	calculates the interaction energy between the selections.

	If apply_sm is True, the SimpleMetric calculation will be added to the 
	pose energies list and output by the job distributor 
	"""
	from pyrosetta.rosetta.core.simple_metrics.metrics import \
		InteractionEnergyMetric

	interact_metric = InteractionEnergyMetric()
	interact_metric.set_scorefunction(score_function)
	interact_metric.set_residue_selectors(selection_1, selection_2)

	if apply_sm:
		interact_metric.apply(pose)
	
	return interact_metric.calculate(pose)


def calc_single_res_intEs(pose, score_function, focus_selection, 
	interaction_target):
	"""
	For a given pose and score function, returns a list of single-residue
	interaction energies for all residues in a focus selection with a 
	specified target selection.
	"""
	intE_list = []
	for res in selector_to_list(pose, focus_selection):
		res_selection = index_selector(res)
		intE = interaction_energy(pose, score_function, res_selection, 
			interaction_target)
		intE_list.append(intE)

	return intE_list


def calc_single_res_intra_selection_intEs(pose, score_function, 
	focus_selection, sub_selection=None):
	"""
	For a given pose and score function, returns a list of single-residue
	interaction energies for all residues within a focus selection with all 
	other residues in that selection. Providing a sub_selection that includes
	a subset of the focus_selection will result in the energies for only the 
	residues in the sub_selection being calculated.
	"""
	# Determine restricted selection
	if sub_selection == None:
		sub_selection = focus_selection

	# Calculate per-res intra-selection interaction energies
	intE_list = []
	for res in selector_to_list(pose, sub_selection):
		res_selection = index_selector(res)
		not_res_selection = selector_intersection(focus_selection, 
			not_selector(res_selection))
		intE = interaction_energy(pose, score_function, res_selection, 
			not_res_selection)
		intE_list.append(intE)

	return intE_list


def calc_ddg(pose, score_function=None, jump=1, apply_sm=False):
	"""
	Calculates the interfacial change in free energy resulting from binding. 
	This differs from interaction energy in that it involves a repack of the 
	side chains before calculating the energy change, whereas interaction energy
	is based on the static structure. 

	If no score function is given, a default ref15 will be used.

	By default, the ddG is calculated across the first jump in the pose.

	If apply_sm is True, the SimpleMetric calculation will be added to the 
	pose energies list and output by the job distributor
	"""
	from pyrosetta.rosetta.protocols.simple_ddg import ddG

	# Set score function
	if score_function == None:
		score_function = get_sf(constrain=0)

	# Create the scoring metric
	ddg = ddG(score_function, jump)

	# Apply to pose or at least calculate
	if apply_sm:
		ddg.apply(pose)
	else:
		ddg.calculate(pose)

	return ddg.sum_ddG()


def ddg_of_selections(pose, score_function, selection_1, selection_2, 
	dump_pdb=False):
	"""
	Estimates binding ddG between two selections by creating separate poses for
	each selection and repacking and minimizing them separately and comparing 
	the total score of the complex to the sum of total scores of the separate 
	parts.

	If you want to output the repacked/minimized PDBs generated by this 
	calculation, specify a name in the dump_pdb argument. Outputted models will
	be {name}_full.pdb, {name}_par1_1.pdb, and {name}_part_2.pdb
	"""
	# Creating poses of the different parts
	part_1_pose = delete_selection_mover(pose, selection_2)
	part_2_pose = delete_selection_mover(pose, selection_1)

	# Repack poses
	tf = make_task_factory() # All packable, nothing designable
	full_pose = pack_mover(pose, score_function, tf)
	part_1_pose = pack_mover(part_1_pose, score_function, tf)
	part_2_pose = pack_mover(part_2_pose, score_function, tf)

	# Minimize 
	full_pose = min_mover(pose, score_function)
	part_1_pose = min_mover(part_1_pose, score_function)
	part_2_pose = min_mover(part_2_pose, score_function)

	# Calculate scores
	full_score = total_energy(pose, score_function)
	part_1_score = total_energy(part_1_pose, score_function)
	part_2_score = total_energy(part_2_pose, score_function)
	ddg = full_score - (part_1_score + part_2_score)

	# Outputting models
	if dump_pdb:
		full_pose.dump_pdb(
			output_file_name(dump_pdb, extension='pdb', suffix='full'))
		part_1_pose.dump_pdb(
			output_file_name(dump_pdb, extension='pdb', suffix='part_1'))
		part_2_pose.dump_pdb(
			output_file_name(dump_pdb, extension='pdb', suffix='part_2'))

	return ddg


def print_pose_scores(pose):
	"""
	Prints all energies in a pose that have a non-zero weight in REF2015
	Note that scores are unweighted.
	"""
	nonzeros = ['fa_atr', 'fa_rep', 'fa_sol', 'fa_intra_rep', 
		'fa_intra_sol_xover4', 'lk_ball_wtd', 'fa_elec', 'pro_close', 
		'hbond_sr_bb', 'hbond_lr_bb', 'hbond_bb_sc', 'hbond_sc', 'dslf_fa13', 
		'atom_pair_constraint', 'coordinate_constraint', 'angle_constraint', 
		'dihedral_constraint', 'metalbinding_constraint', 'omega', 'fa_dun', 
		'p_aa_pp', 'yhh_planarity', 'ref', 'chainbreak', 'rama_prepro', 
		'res_type_constraint', 'total_score']

	pose_energies = pose.energies().total_energies()
	listed_scores = pose_energies.show_nonzero().split()
	listed_scores = [i.rstrip(':') for i in listed_scores]
	for i in nonzeros:
		if i in listed_scores:
			print("{:<40}{}".format(i, listed_scores[listed_scores.index(i)+1]))
		else:
			print("{:<40}{}".format(i, 0))

################################################################################
# Constraints functions (functions require PyRosetta)

def apply_enzdes_constraints(pose, cst_file):
	""" 
	Applies the constraints form the input CST file to a pose. Returns 
	constraied pose.
	"""
	from pyrosetta import Pose
	from pyrosetta.rosetta.protocols.enzdes import ADD_NEW, AddOrRemoveMatchCsts

	cstm = AddOrRemoveMatchCsts()
	cstm.set_cst_action(ADD_NEW)
	cstm.cstfile(cst_file)

	# Copy pose and apply constraints
	constrained_pose = Pose(pose)
	cstm.apply(constrained_pose)

	return constrained_pose


def apply_coord_constraints(pose, selection=None, sidechains=False, 
	bounded=True):
	""" 
	Applies backbone coordinate constraints to a selection of a pose Returns 
	constraied pose.
	"""
	from pyrosetta import Pose
	from pyrosetta.rosetta.protocols.constraint_generator import \
	AddConstraints, CoordinateConstraintGenerator

	cg = CoordinateConstraintGenerator()
	cg.set_sidechain(sidechains)

	if selection:
		cg.set_residue_selector(selection)

	if bounded:
		cg.set_bounded(True)	
		cg.set_bounded_width(0.1)
		cg.set_sd(0.5)

	ac = AddConstraints()
	ac.add_generator(cg)

	# Copy pose and apply constraints
	constrained_pose = Pose(pose)
	ac.apply(constrained_pose)

	return constrained_pose


def apply_res_type_constraints(pose, penalty=0.5):
	""" Apply residue type constraints to a pose """
	from pyrosetta import Pose
	from pyrosetta.rosetta.protocols.protein_interface_design import \
	FavorNativeResidue

	# Copy pose and apply constraints
	constrained_pose = Pose(pose)
	FavorNativeResidue(constrained_pose, penalty)
	return constrained_pose


def apply_distance_constraints(pose, residue_1, atom_1, residue_2, atom_2, 
	distance, sd):
	"""
	Adds specified distance constraints to a pose. Uses a harmonic constraint 
	function with a specifiable standard deviation. Input a pose and two residue 
	numbers with the correspondig atoms for each residue. If distance is set to 
	0, will use the current distance.

	The pose is modified and the function has an empty return.

	Example:
	apply_distance_constraints(pose, 10, 'CA', 20, 'CA', 5, 0.5)
	"""
	from pyrosetta.rosetta.core.scoring.constraints import AtomPairConstraint
	from pyrosetta.rosetta.core.scoring.func import HarmonicFunc

	# Determine atoms to constrain
	a1 = find_atom_id(pose, residue_1, atom_type=atom_1)
	a2 = find_atom_id(pose, residue_2, atom_type=atom_2)

	# Adjust distance if current distance is desired
	if distance == 0:
		distance = calc_distance(a1, a2)

	# Create harmonic score function with specified distance and sd
	harm_func = HarmonicFunc(distance, sd)

	# Create the constraint
	distance_constraint = AtomPairConstraint(a1, a2, harm_func)

	# Add the constraint to the pose
	pose.add_constraint(distance_constraint)

	return pose


def apply_dihedral_constraint(pose, residue, dihedral, angle, sd=5):
	"""
	This function allows for the addition of a specified dihedral constraint to
	a pose. Uses a circular harmonic constraint function with a specifiable 
	standard deviation (default 5). 

	Specify the pose, which residue within the pose (pose numbering, not PDB), 
	which dihedral to set ('phi', 'psi', or 'omega'), and the desired angle (in 
	degrees, not radians). If a looser or tighter constraint is desired, alter 
	the sd of the harmonic function. 

	The pose is modified and the function has an empty return.
	"""
	from math import radians
	from pyrosetta.rosetta.core.scoring.constraints import DihedralConstraint
	from pyrosetta.rosetta.core.scoring.func import CircularHarmonicFunc

	# Create circular harmonic score function with specified angle and sd
	circ_harm_func = CircularHarmonicFunc(radians(angle), radians(sd))

	# Determine appropriate atoms for the desired residue and dihedral
	dihedral_atom_ids = find_dihedral_atom_ids(pose, residue, dihedral)

	# Create the constraint
	dihedral_constraint = DihedralConstraint(*dihedral_atom_ids, circ_harm_func)

	# Add the constraint to the pose
	pose.add_constraint(dihedral_constraint)

	return pose


def constrain_current_backbone_dihedrals(pose, selection, sd=5):
	"""
	Given a Pose and a ResidueSelector, adds constraints to the pose to enforce
	the current backbone dihedrals (phi and psi) of the selected residues, using
	a circular harmonic constraint function with a specifiable standard 
	deviation (default 5).

	The pose is modified and the function has an empty return.
	"""
	# Convert selection into a list of residues
	residues_to_constrain = selector_to_list(pose, selection)

	# Add constraints to each selected phi and psi
	for res in residues_to_constrain:
		# Phi angle
		current_phi = pose.phi(res)
		apply_dihedral_constraint(pose, res, 'phi', current_phi, sd=sd)

		# Psi angle
		current_psi = pose.psi(res)
		apply_dihedral_constraint(pose, res, 'psi', current_psi, sd=sd)

	return pose

################################################################################
# Mover functions (functions require PyRosetta)

def make_move_map(bb=False, chi=False, jump=False):
	"""
	Creates a Rosetta MoveMap. By default, all backbone, chi, and jumps will be
	immobile. Arguments can be either booleans or lists/iterables. If a list of  
	residue numbers is given, all residues in the list will be mobile, and  
	everything else will be immobile.

	Example:
	make_move_map(bb=False, chi=[1,2,3], jump=False)
	"""
	from pyrosetta import MoveMap

	# Create move map
	movemap = MoveMap()

	# Backbone
	if isinstance(bb, bool):
		movemap.set_bb(bb)
	else:
		for res in bb:
			movemap.set_bb(res, True)

	# Side chains
	if isinstance(chi, bool):
		movemap.set_chi(chi)
	else:
		for res in chi:
			movemap.set_chi(res, True)

	# Side chains
	if isinstance(jump, bool):
		movemap.set_chi(jump)
	else:
		for j in jump:
			movemap.set_chi(j, True)

	return movemap


def make_task_factory(design_selection=None, repack_selection=None, 
	immobile_selection=None, res_changes=None, ex12=True):
	"""
	Generates a task factory for subsequent use in movers. When called with no 
	arguments, produces a task factory that will repack (no design) the whole
	pose with an ex1 ex2 rotamer library.

	If a design_selection is given, those residues will be designable and 
	everyhting else will by default remain repackable. 

	If a repack_selection is given, then those residues shall be repacked, and
	all others shall be kept immobile unless they are designable or part of a 
	residue change. Designable and residue changes supersede repackable.

	An immobile_selection will prevent any selected residues from being included
	in any form of repacking, superseding design, repack, or residue changes.

	res_changes shold be a dict where the keys are the pose-numbered sites of
	residues to have their sequence changed, and the values are the 1-letter
	amino acid name to which that residue should be changed.

	The ex12 option, True by default, activates the expanded rotamer library.
	"""
	from pyrosetta.rosetta.core.pack.task import TaskFactory
	import pyrosetta.rosetta.core.pack.task.operation as taskop

	# Initialize selections
	if design_selection == None:
		design_selection = empty_selector()
	if repack_selection == None:
		repack_selection = full_selector()
	if immobile_selection == None:
		immobile_selection = empty_selector()

	# Initialize task factory
	tf = TaskFactory()
	tf.push_back(taskop.IncludeCurrent())
	tf.push_back(taskop.NoRepackDisulfides())

	# Add extra rotamers
	if ex12:
		tf.push_back(taskop.ExtraRotamers(0, 1, 1))
		tf.push_back(taskop.ExtraRotamers(0, 2, 1))

	# Add residue changes to task factory and designable selection
	if res_changes:
		for site, aa in res_changes.items():
			res_selection = index_selector(str(site))
			restriction = taskop.RestrictAbsentCanonicalAASRLT()
			restriction.aas_to_keep(aa.upper())
			tf.push_back(
				taskop.OperateOnResidueSubset(restriction,res_selection))
			design_selection = selector_union(design_selection, res_selection)

	# Subtract immobile residues from designable and repackable selections
	design_selection = selector_intersection(design_selection, 
		not_selector(immobile_selection))
	repack_selection = selector_intersection(repack_selection, 
		not_selector(immobile_selection))

	# Subtract designable residues from those restricted to repacking
	repack_selection = selector_intersection(repack_selection, 
		not_selector(design_selection))

	# Update immobile selection to take all residues not designable or packable
	immobile_selection = not_selector(
		selector_union(design_selection, repack_selection))

	# Restrict repackable selection to repacking
	restrict = taskop.RestrictToRepackingRLT()
	tf.push_back(taskop.OperateOnResidueSubset(restrict, repack_selection))

	# Prevent repacking of immobile selection
	prevent = taskop.PreventRepackingRLT()
	tf.push_back(taskop.OperateOnResidueSubset(prevent, immobile_selection))

	return tf


def pack_mover(pose, score_function, task_factory):
	"""
	Apply a repack mover on a pose using a given score fuction and task factory
	"""
	from pyrosetta import Pose
	from pyrosetta.rosetta.protocols.minimization_packing import \
		PackRotamersMover

	# Create mover
	prm = PackRotamersMover(score_function)
	prm.task_factory(task_factory)

	# Copy pose and apply the mover
	packed_pose = Pose(pose)
	prm.apply(packed_pose)

	return packed_pose


def min_mover(pose, score_function, move_map=None):
	"""
	Apply a minimization mover on a pose using a given score fuction. A move map
	can optionally be applied as well.
	"""
	from pyrosetta import Pose
	from pyrosetta.rosetta.protocols.minimization_packing import \
		MinMover

	# Create mover
	min_mover = MinMover()
	min_mover.score_function(score_function)
	if move_map:
		min_mover.movemap(movemap)

	# Copy pose and apply the mover
	minimized_pose = Pose(pose)
	min_mover.apply(minimized_pose)

	return minimized_pose


def fast_relax_mover(score_function=None, task_factory=None, movemap=None, 
	repeats=5):
	"""
	Creates a FastRelax mover. If no score function is given, a default 
	ref15_cst will be used. If a task factory and/or movemap are provided, 
	they will also be incorporated into the mover. By default, FastRelax 
	goes through five ramping cycles, but this number can be adjusted with 
	the repeats option.
	"""
	from pyrosetta.rosetta.protocols.relax import FastRelax

	# Make FastRelax mover with given score function
	fr = FastRelax(repeats)

	# Set score function
	if score_function == None:
		score_function = get_sf()
	fr.set_scorefxn(score_function)

	# Set task factory
	if task_factory:
		fr.set_task_factory(task_factory)

	# Set move map
	if movemap:
		fr.set_movemap(movemap)

	return fr


def delete_selection_mover(pose, selection):
	"""
	Deletes a region of a pose specified by a residue selector
	"""
	from pyrosetta import Pose
	from pyrosetta.rosetta.protocols.grafting.simple_movers import \
		DeleteRegionMover 

	# Create mover
	drm = DeleteRegionMover()
	drm.set_residue_selector(selection)

	# Make trimmed pose
	trimmed_pose = Pose(pose)
	drm.apply(trimmed_pose)

	return trimmed_pose


def split_ensemble_pose(pose, only_first_state=False):
	"""
	Some PDBs include multiple states of the protein (such as NMR ensembles).
	This function takes a pose with multiple states and returns a list of poses
	with each state as a separate pose. If multiple chains are present, it is 
	assumed that the order of states is consistent across all chains.
	"""
	# Create dict to track states for multiple chains
	chain_states = {}

	# Go through all chains, identifying chain letter and adding to dict
	for chain in range(1, pose.num_chains() + 1):
		# Determine chain ID
		chain_start = pose.chain_begin(chain) 
		chain_id = pose.pdb_info().pose2pdb(chain_start).split()[1]

		# Add chain to states dict
		if chain_id not in chain_states:
			chain_states[chain_id] = [chain]
		else:
			chain_states[chain_id].append(chain)

	# Determine number of states
	state_counts = [len(i) for i in chain_states.values()]
	num_states = state_counts[0]
	assert state_counts.count(num_states) == len(state_counts)

	# Create trimmed poses
	single_state_poses = []
	for state in range(num_states):
		# Select the chains corresponding to this state
		chains_for_this_state = []
		for states in chain_states.values():
			chains_for_this_state.append(chain_selector(states[state]))
		keeps_selection = selector_union(*chains_for_this_state)

		# Delete everything but the selected chains
		single_state_poses.append(
			delete_selection_mover(pose, not_selector(keeps_selection)))

		if only_first_state:
			break

	return single_state_poses


def extract_pose_chain(pose, chain):
	"""
	Returns a pose that is only a single specified chain. Chain can be either a 
	letter or an integer. Function requires PyRosetta to be initialized. If a 
	PDB includes multiple states (ex: an NMR ensemble), takes the first state.
	"""
	from pyrosetta import Pose 

	# No need to extract if the pose has only one chain
	if pose.num_chains() == 1:
		return Pose(pose)

	# Reduce ensemble to single state
	pose = split_ensemble_pose(pose, only_first_state=True)[0]

	# Determine terminal residues of the target chain
	# Integer case
	if isinstance(chain, int):
		chain_start = pose.chain_begin(chain)
		chain_end = pose.chain_end(chain)

	# Letter case
	else:
		for c in range(1, pose.num_chains() + 1):
			chain_start = pose.chain_begin(c)
			chain_id = pose.pdb_info().pose2pdb(chain_start).split()[1]
			if chain_id == chain:
				chain_end = pose.chain_end(c)
				break

	return Pose(pose, chain_start, chain_end)


def pyjobdistributor(decoy_name, n_decoys, scorefxn):
	"""
	Creates a PyJobDistributor
	"""
	from pyrosetta import PyJobDistributor

	return PyJobDistributor(decoy_name, n_decoys, scorefxn)



