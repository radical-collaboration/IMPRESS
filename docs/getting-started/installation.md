# 🧰 Installation Guide

This page shows you how to set up your environment to use **Impress** and run asynchronous pipelines with it.  

We recommend using a **virtual environment** to isolate your dependencies.

---

## 📦 Step 1: Create a Python Environment

Make sure you have **Python 3.8 or newer** installed.  
You can check your Python version with:

```bash
python3 --version
```

We recommend creating a virtual environment to keep dependencies clean.

### Using `venv`

On Linux/Mac:

```bash
python3 -m venv impress-env
source impress-env/bin/activate
```

On Windows:

```bash
python -m venv impress-env
impress-env\Scripts\activate
```

Your shell prompt should now show `(impress-env)` indicating the environment is active.

---

## 🚀 Step 2: Install Impress

Install **Impress** and its required dependencies from PyPI:

```bash
pip install impress
```

Impress uses **Radical AsyncFlow** as its workflow backend.  
If not installed automatically, you can install it explicitly:

```bash
pip install radical-asyncflow
```

---

## 🧪 Step 3: Verify Installation

Check that Impress is installed and importable:

```bash
python -c "from impress import ImpressManager; print('Impress is installed!')"
```

You should see:

```
Impress is installed!
```

---

## 🧬 Step 4: Run a Sample Pipeline

Now you’re ready to write and run your own pipelines!  
You can follow the [Tutorial: Submit N Pipelines Asynchronously](tutorials/async_protein_pipelines.md) to get started.

---

## 🔄 Deactivate Environment

When you’re done, you can deactivate your virtual environment:

```bash
deactivate
```

Next time you want to work with Impress, just activate the environment again.

---

## 📚 Next Steps

✅ [Tutorial: Submit N Pipelines Asynchronously](tutorials/async_protein_pipelines.md)  
✅ Explore the API reference  
✅ Build your own workflows!

---