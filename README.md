# SpeedPy Standard Project

This is a standard project to start your Django based webapps.

## Key features

- Following 12 Factor app uses environment variables for configuration
- Custom User model in a separate app `usermodel`
- Single Django app project layout, except `usermodel`
- Celery
- Tailwind

## Requirements

- You must have Docker installed on your machine.
- Linux or Mac
- Git installed and configured (`user.name` and `user.email`)
- 

## How to use

### If you have already cloned the repo

To initialize environment please type in terminal in the root of the project:

```bash
bash init.sh
```

### One line download and start

Run this command if you haven't cloned the code:

```
wget -qO- https://speedpy.com/install | bash
```

### Tailwind

(This section needs rewrite when we update tailwind)

There is Tailwind configuration file (`tailwind.config.js`) in the root of the project.

To use Tailwind, you need to have Node installed in your computer first. Go to [Node.js](https://nodejs.org/en/) and download the installer for your operating system. Follow the instructions to install Node.js and npm.

(Not sure if you have Node installed? Run `node -v` and `npm -v` in your terminal. If you get a version number in response, you have Node.js installed.)

In addition to Tailwind, this project uses [Flowbite](https://flowbite.com), a set of components and utilities for Tailwind CSS. It's included in the `tailwind.config.js` file.

(Not sure why you have a reference to the Tailwind installation here, so maybe consider removing it?)
See [Tailwind Installation](https://tailwindcss.com/docs/installation).

#### Generating Tailwind Directories

(This section needs rewrite when we update tailwind)

In order for tailwind know where all Django apps' templates and static files are located you need to run:

This will first activate the virtual environment:
```bash
source env/bin/activate
```
Then:
```bash
python manage.py generate_tailwind_directories
```

This will populate the `tailwind_directories.json` file which is used in the `tailwind.config.js` configuration file.

#### Compiling Tailwind

(This section needs rewrite when we update tailwind)

In order to turn Tailwind CSS into regular CSS, you need to run the following command:

To compile CSS once, run:(running this gives error: npm ERR! missing script: build:css)
The correct command should be: `npm run tailwind:build`
```bash
npm run build:css
```

Alternatively, you can use make:

```bash
make tw-build
```

#### Watching Tailwind (for changes)

(This section needs rewrite when we update tailwind)

To avoid having to run the above commands everytime you make changes to your templates using Tailwind, you can run the below command to watch for changes and recompile CSS automatically:
(this also gives the same error as above, the correct command should be: `npm run tailwind:watch`)
```bash
npm run watch:css
```

Or use the shortcut:

```bash
make tw
```


### Running the project

(This section needs rewrite when we update tailwind)

To run the project, type in terminal in the root of the project:

```bash
source env/bin/activate
python manage.py runserver

```

Or shorter, with `make`:

```bash
make run
```


## Project Structure

(This section needs rewrite when we update tailwind)

The project structure is based on the idea of a Single App Django Project
Layout. [Watch the video](https://youtu.be/R7y1MkzOk7o?si=bzxWTvF7Wtyl2yW7) for the reasoning behind it and detailed explanation.

Actually two apps are present: `mainapp` and `usermodel`. But the majority of changes you'll be making in the `mainapp`
app.

Here is the tree with key files and directories listed:

```
├── README.md
├── mainapp
│   ├── __init__.py
│   ├── admin
│   │   └── __init__.py
│   ├── apps.py
│   ├── forms
│   │   └── __init__.py
│   ├── migrations
│   │   └── __init__.py
│   ├── models
│   │   └── __init__.py
│   └── views
│       ├── __init__.py
│       └── welcome.py
├── package.json
├── project
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── requirements.txt
├── static
├── tailwind.config.js
├── templates
└── usermodel
```

### mainapp

The main app is where you will be putting your code.

Instead of typical files, like `views.py` or `models.py`, you'll find directories with similar names. These are Python
packages. The reason for this is that it's easier to split your code into multiple files this way.

Since we have only one app, we don't really need to create a separate `urls.py` file, so the whole URL configuration is
in `project/urls.py`. If you choose to have it separate, you can create a `urls.py` file in the `mainapp` directory and
import it in the `project/urls.py`
file. [Including other URLconfs](https://docs.djangoproject.com/en/5.0/topics/http/urls/#including-other-urlconfs)

For example this is where you would add a model, a view and a form:

```
├── mainapp
│   ├── __init__.py
│   ├── admin
│   │   └── __init__.py
│   ├── apps.py
│   ├── forms
│   │   ├── __init__.py  #  <-- needs change
│   │   └── expenses.py  #  <-- new file, where you put form(s)
│   ├── models
│   │   ├── __init__.py  #  <-- needs change
│   │   └── expenses.py  #  <-- new file, where you put your model(s)
│   └── views
│       ├── __init__.py  #  <-- needs change
│       ├── expenses.py  #  <-- new file, where you put your view(s)
│       └── welcome.py
```

The `__init__.py` file is used to mark a directory as a Python package, which means that it can be imported and treated as a module. The `__init__.py` file is executed when the package is imported, allowing you to perform any necessary initialization or configuration.

In the `__all__` variable in the `__init__.py` file you can list modules or symbols should be imported when using the `from package import *` syntax. When you use the `from mainapp.forms import *` syntax, only the modules or symbols listed in the `__all__` variable will be imported.

General advice is to group your models/views/forms in files named according to their area of responsibility.

If you need to refer a model from another model in a `ForeignKey` to avoid circular dependency instead of importing it, use a string with dotted notation.

E.g. if you have two models, a `Category` model and a `Book` model, and `Book` needs a `ForeignKey` to the `Category` model

instead of:

```python
from .category import Category

class Book(models.Model):
    category = models.ForeignKey(Category)
```

Do this instead:

```python
# no import here
class Book(models.Model):
    category = models.ForeignKey('mainapp.Category')
```

### usermodel

Structure of the app:

```
.
├── __init__.py
├── admin.py
├── apps.py
├── management
│   ├── __init__.py
│   └── commands
│       ├── __init__.py
│       └── makesuperuser.py
├── managers.py
├── migrations
│   ├── 0001_initial.py
│   └── __init__.py
├── models.py
├── tests.py
└── views.py
```

This app holds the custom user model. It's a good idea to keep it separate from the main app, since it will be pretty
static and you won't be changing it often.

This `Custom User` model has email as a login field.

The `email` field is case-insensitive. (This next sentences are not very clear to me): Also, the initial migration for this field is created with collation set to `db_collation=settings.CI_COLLATION` and `CI_COLLATION` is it `project/settings.py` depending on the database you are using.

## How to work on the project
Add your models in new files under `mainapp/models/` directory. Then add the model to `mainapp/models/__init__.py` file. This way you can split your models into multiple files.

Add your views in new files under `mainapp/views/` directory. Then add the view to `mainapp/views/__init__.py` file. 

Add your forms in new files under `mainapp/forms/` directory. Then add the form to `mainapp/forms/__init__.py` file. 

Templates for the app go into the root `templates` directory under `mainapp` subdirectory. For example, if you have a view `mainapp.views.home`, then the template should be at `templates/mainapp/home.html`.

The root `templates` directory is great because you can override templates from other apps.

## Deploy with Appliku

Already includes `appliku.yml` file which will automatically configure your application within Appliku.

* Create your app
* Change the build image to Python 3.12 + node 20.10
* Set the "Build command" to: `npm i && make tw-build`
* Create Postgres 16 and Redis 7 databases
* Add environment variables:
  * ALLOWED_HOSTS – if you have multiple domains make it a comma separated without spaces
  * SECRET_KEY
  * CELERY_BROKER_URL - use value of REDIS_URL or use RabbitMQ
* Create processes:
  * `web`: `web.sh`
  * `release`: `bash release.sh`
  * `celery`: `bash celery-worker.sh`
  * `beat`: `bash celery-beat.sh`

