import time

from django import forms
from django.conf import settings
from django.utils.crypto import salted_hmac, constant_time_compare
from django.utils.hashcompat import sha_constructor
from django.utils.translation import ugettext_lazy as _

from tcc.models import Comment


class CommentForm(forms.ModelForm):
    """
    Handles the security aspects (anti-spoofing) for comment forms.
    """
    timestamp = forms.IntegerField(widget=forms.HiddenInput)
    security_hash = forms.CharField(min_length=40, max_length=40,
                                    widget=forms.HiddenInput)
    next = forms.CharField(widget=forms.HiddenInput, required=False)
    honeypot = forms.CharField(
        required=False,
        label=_('If you enter anything in this field '\
                    'your comment will be treated as spam'),
        widget=forms.HiddenInput,
    )

    def __init__(self, data=None, initial=None, ip=None):
        self.data = data
        self.initial = initial or {}
        self.initial.update(self.generate_security_data())
        self.ip = ip
        super(CommentForm, self).__init__(data=data, initial=self.initial)

    def save(self, commit=True):
        instance = forms.ModelForm.save(self, commit=False)
        assert self.ip, 'Unable to save without an IP address'
        instance.ip_address = self.ip
        if commit:
            instance.save()
        return instance

    @property
    def content_type(self):
        content_type = self.initial.get('content_type')
        if not content_type:
            content_type = self.data['content_type']
        return content_type

    @property
    def object_pk(self):
        object_pk = self.initial.get('object_pk')
        if not object_pk:
            object_pk = self.data['object_pk']
        return object_pk

    def clean_honeypot(self):
        """Check that nothing's been entered into the honeypot."""
        value = self.cleaned_data["honeypot"]
        if value:
            raise forms.ValidationError(self.fields["honeypot"].label)
        return value

    def security_errors(self):
        """Return just those errors associated with security"""
        errors = forms.ErrorDict()
        for f in ["honeypot", "timestamp", "security_hash"]:
            if f in self.errors:
                errors[f] = self.errors[f]
        return errors

    def clean_security_hash(self):
        """Check the security hash."""
        security_hash_dict = {
            'content_type' : self.data.get("content_type", ""),
            'object_pk' : self.data.get("object_pk", ""),
            'timestamp' : self.data.get("timestamp", ""),
        }
        expected_hash = self.generate_security_hash(**security_hash_dict)
        actual_hash = self.cleaned_data["security_hash"]
        if not constant_time_compare(expected_hash, actual_hash):
  # Fallback to Django 1.2 method for compatibility
  # PendingDeprecationWarning <- here to remind us to remove this
  # fallback in Django 1.5
            expected_hash_old = self._generate_security_hash_old(**security_hash_dict)
            if not constant_time_compare(expected_hash_old, actual_hash):
                raise forms.ValidationError("Security hash check failed.")
        return actual_hash

    def clean_timestamp(self):
        """Make sure the timestamp isn't too far (> 2 hours) in the past."""
        ts = self.cleaned_data["timestamp"]
        if time.time() - ts > (2 * 60 * 60):
            raise forms.ValidationError("Timestamp check failed")
        return ts

    def generate_security_data(self):
        """Generate a dict of security data for "initial" data."""
        timestamp = int(time.time())
        security_dict =   {
            'content_type'  : str(self.content_type),
            'object_pk'     : str(self.object_pk),
            'timestamp'     : str(timestamp),
            'security_hash' : self.initial_security_hash(timestamp),
        }
        return security_dict

    def initial_security_hash(self, timestamp):
        """
        Generate the initial security hash from self.content_object
        and a (unix) timestamp.
        """

        initial_security_dict = {
            'content_type' : str(self.content_type),
            'object_pk' : str(self.object_pk),
            'timestamp' : str(timestamp),
        }
        return self.generate_security_hash(**initial_security_dict)

    def generate_security_hash(self, content_type, object_pk, timestamp):
        """
        Generate a HMAC security hash from the provided info.
        """
        info = (content_type, object_pk, timestamp)
        key_salt = "django.contrib.forms.CommentSecurityForm"
        value = "-".join(info)
        return salted_hmac(key_salt, value).hexdigest()

    def _generate_security_hash_old(self, content_type, object_pk, timestamp):
        """Generate a (SHA1) security hash from the provided info."""
  # Django 1.2 compatibility
        info = (content_type, object_pk, timestamp, settings.SECRET_KEY)
        return sha_constructor("".join(info)).hexdigest()

    class Meta:
        model = Comment
        fields = [
            'content_type',
            'object_pk',
            'parent',
            'user',
            'comment',
            'timestamp',
            'security_hash',
            'next',
            'honeypot',
        ]
        widgets = {
            'content_type': forms.HiddenInput,
            'object_pk': forms.HiddenInput,
            'user': forms.HiddenInput,
            'parent': forms.HiddenInput,
        }

