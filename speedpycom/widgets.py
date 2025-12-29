from django import forms


class ColorInput(forms.TextInput):
    input_type = "color"
    template_name = "speedpycom/fields/color_picker.html"