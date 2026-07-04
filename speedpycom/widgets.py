from django import forms


class ColorInput(forms.TextInput):
    input_type = "color"
    template_name = "speedpycom/fields/color_picker.html"


class ImageUploadInput(forms.ClearableFileInput):
    """Drop-in replacement for ClearableFileInput on ImageFields.

    Renders a thumbnail of the current image, a drag & drop zone with live
    preview of the newly selected file, and a Remove button wired to the
    standard clear checkbox, so no view/form logic changes are needed.
    """

    template_name = "speedpycom/fields/image_upload.html"

    def __init__(self, attrs=None):
        attrs = {"accept": "image/*", **(attrs or {})}
        super().__init__(attrs)