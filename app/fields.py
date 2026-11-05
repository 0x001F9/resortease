from django import forms
from django.db import models


def normalize_title_case(value):
    if isinstance(value, str):
        return value.strip().title()
    return value


class TitleCaseFormField(forms.CharField):
    def to_python(self, value):
        return normalize_title_case(super().to_python(value))


class TitleCaseCharField(models.CharField):
    def to_python(self, value):
        return normalize_title_case(super().to_python(value))

    def formfield(self, **kwargs):
        kwargs.setdefault("form_class", TitleCaseFormField)
        return super().formfield(**kwargs)

    def pre_save(self, model_instance, add):
        value = super().pre_save(model_instance, add)
        value = self.to_python(value)
        setattr(model_instance, self.attname, value)
        return value
