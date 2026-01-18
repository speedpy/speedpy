from crispy_forms.bootstrap import Alert as BaseAlert
from crispy_forms.layout import BaseInput, Field, LayoutObject, TEMPLATE_PACK
from django.template.loader import render_to_string


class Submit(BaseInput):
    """
    Used to create a Submit button descriptor for the {% crispy %} template tag::
        submit = Submit('Search the Site', 'search this site')
    .. note:: The first argument is also slugified and turned into the id for the submit button.

    This is a customised version for Tailwind to add Tailwind CSS style by default
    """

    input_type = "submit"

    def __init__(self, *args, css_class=None, **kwargs):
        if css_class is None:
            self.field_classes = "bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded"
        else:
            self.field_classes = css_class
        super().__init__(*args, **kwargs)


class Reset(BaseInput):
    """
    Used to create a Reset button input descriptor for the {% crispy %} template tag::
        reset = Reset('Reset This Form', 'Revert Me!')
    .. note:: The first argument is also slugified and turned into the id for the reset.

    This is a customised version for Tailwind to add Tailwind CSS style by default
    """

    input_type = "reset"

    def __init__(self, *args, css_class=None, **kwargs):
        if css_class is None:
            self.field_classes = "bg-red-500 hover:bg-red-700 text-white font-bold py-2 px-4 rounded"
        else:
            self.field_classes = css_class
        super().__init__(*args, **kwargs)


class Button(BaseInput):
    """
    Used to create a button descriptor for the {% crispy %} template tag::
        submit = Button('Search the Site', 'search this site')
    .. note:: The first argument is also slugified and turned into the id for the submit button.

    This is a customised version for Tailwind to add Tailwind CSS style by default
    """

    input_type = "button"

    def __init__(self, *args, css_class=None, **kwargs):
        if css_class is None:
            self.field_classes = "bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"
        else:
            self.field_classes = css_class
        super().__init__(*args, **kwargs)


class Alert(BaseAlert):
    css_class = ""


class BooleanField(Field):
    """
    Custom BooleanField that automatically uses the checkbox.html template.
    Provides consistent styling for all checkbox fields.

    Note: As of the auto-routing implementation, this is no longer needed
    for standard checkbox fields - they are automatically routed to the
    checkbox template. This class is kept for backward compatibility.

    Usage:
        BooleanField('is_active')

    You can still override the template if needed:
        BooleanField('special_checkbox', template='custom/template.html')
    """
    def __init__(self, *args, **kwargs):
        if 'template' not in kwargs:
            kwargs['template'] = 'tailwind/layout/checkbox.html'
        super().__init__(*args, **kwargs)


class Collapse(LayoutObject):
    """
    Collapsible section with Alpine.js toggle behavior.

    Usage:
        Collapse(
            "Section Title",
            Field('field1'),
            Field('field2'),
            HTML('<p>Help text</p>'),
        )

    Advanced usage with custom state variable:
        Collapse(
            "Authentication",
            Field('auth_type'),
            state_var='authOpen',
            default_open=False
        )
    """
    template = "tailwind/layout/collapse.html"

    def __init__(self, label, *fields, **kwargs):
        self.label = label
        self.fields = list(fields)
        self.state_var = kwargs.pop('state_var', 'open')
        self.default_open = kwargs.pop('default_open', False)
        self.extra_context = kwargs.pop('extra_context', {})

    def render(self, form, context, template_pack=TEMPLATE_PACK, **kwargs):
        fields_output = ''.join(
            field.render(form, context, template_pack=template_pack, **kwargs)
            for field in self.fields
        )

        template_context = {
            'label': self.label,
            'state_var': self.state_var,
            'default_open': self.default_open,
            'fields_output': fields_output,
            **self.extra_context
        }

        return render_to_string(self.template, template_context)
