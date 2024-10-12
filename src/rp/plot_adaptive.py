import os
import pandas as pd
from itertools import cycle
colors_list=cycle('bgrcmyk')
struct=[]
for files in os.listdir('p1_in/'):
	struct.append(files)
for files in os.listdir('p2_in/'):
	struct.append(files)
md={}
for a in struct:
	temp=[]
	for files in os.listdir('./'):
		print(files)
		if 'af_stats_p' in files:
			df=pd.read_csv(files)
			if a in list(df['ID']):
				for b, c in zip(df['ID'], df['avg_pae']):
					if b == a:
						pipeline_num=int(files.split('_')[2][1:])
						pass_=int(files.split('_')[4].replace('.csv',''))
						temp.append([pass_,pipeline_num,c])
	temp.sort(key=lambda x: (x[0],x[1]))
	md[a]=temp
print(md)
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
fig, axs = plt.subplots(2,2)
ctr1=0
ctr2=0
for a, b in md.items():
	names=[]
	X=[]
	Y=[]
	x=[]
	y=[]
	prev_pae=100
	less=False
	for c in b:
		cur_pass=c[0]
		cur_pname=c[1]
		cur_pae=c[2]	
		if cur_pae < prev_pae:
			x.append(cur_pass)
			y.append(cur_pae)
			prev_pae = cur_pae
			less=True
		else:
			names.append(cur_pname)
			x.append(cur_pass)
			y.append(cur_pae)
			X.append(x)
			Y.append(y)
			x=[]
			y=[]
			less=False
	if less:
		X.append(x)
		Y.append(y)
		names.append(cur_pname)
	
	print(a)
	print(b)
	print(X)
	print(Y)
	for i in range(len(X)):
		axs[ctr1,ctr2].plot(X[i],Y[i],'-o',c=next(colors_list))
	axs[ctr1,ctr2].legend(names)
	axs[ctr1,ctr2].set_title(a)
	axs[ctr1,ctr2].set_xlabel('pass')
	axs[ctr1,ctr2].set_ylabel('interchain_pae')
	axs[ctr1,ctr2].set_xticks([2,3,4,5])
	#plt.savefig(a.replace('.pdb','.png'))
	#plt.close()
	if ctr1 == 1:
		ctr1 = 0
		ctr2 += 1
	else:
		ctr1 += 1
plt.show()