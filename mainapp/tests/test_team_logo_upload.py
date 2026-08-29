"""Team logo uploads are downscaled to 256px and converted to a web-native
format (HEIC/HEIF from iPhone/Mac photos otherwise fail or do not render). See
speedpycom.images.prepare_image, called from TeamSettingsForm.clean_logo.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from mainapp.forms.teams import TeamSettingsForm
from mainapp.models import Team, TeamMembership
from usermodel.models import User

LOGO_MAX = 256


def _heic(size=(1000, 800)):
    import pillow_heif

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", size, (12, 34, 56)).save(buf, format="HEIF")
    return buf.getvalue()


class TeamLogoUploadTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@example.com", password="pw")
        self.team = Team.objects.create(name="Acme", slug="acme")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")

    def _cleaned(self, filename, data, content_type):
        form = TeamSettingsForm(
            data={"name": self.team.name, "slug": self.team.slug, "timezone": "UTC"},
            files={"logo": SimpleUploadedFile(filename, data, content_type=content_type)},
            instance=self.team,
        )
        self.assertTrue(form.is_valid(), form.errors)
        out = form.cleaned_data["logo"]
        out.seek(0)
        return out, Image.open(out)

    def test_heic_logo_converted_to_jpeg_and_downscaled(self):
        out, img = self._cleaned("photo.heic", _heic((1000, 800)), "image/heic")
        self.assertTrue(out.name.endswith(".jpg"), out.name)
        self.assertEqual(img.format, "JPEG")
        self.assertLessEqual(max(img.size), LOGO_MAX)

    def test_large_jpeg_downscaled(self):
        buf = io.BytesIO()
        Image.new("RGB", (1600, 1200), (200, 30, 30)).save(buf, format="JPEG")
        out, img = self._cleaned("logo.jpg", buf.getvalue(), "image/jpeg")
        self.assertEqual(img.size, (256, 192))

    def test_transparent_png_stays_png(self):
        buf = io.BytesIO()
        Image.new("RGBA", (512, 512), (0, 0, 0, 0)).save(buf, format="PNG")
        out, img = self._cleaned("logo.png", buf.getvalue(), "image/png")
        self.assertEqual(img.format, "PNG")
