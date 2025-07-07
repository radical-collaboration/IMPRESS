from setuptools import setup, find_packages

setup(
    name='impress',
    version='0.1.0',
    description='IMPRESS Protein Binding and Prediction Framework for HPC',
    author='Aymen Alsaadi',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=['radical.asyncflow'],
    python_requires='>=3.8',
)
