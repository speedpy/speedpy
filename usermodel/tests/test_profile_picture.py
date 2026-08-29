"""Profile pictures are downscaled + converted to a web-native format on save.

The full-resolution original is never stored (avatars display small), and HEIC
photos (iPhone/Mac) are converted so they render in every browser. Both upload
paths — the profile form and the profile API — go through User.save().
"""

import io
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from usermodel.models import PROFILE_PICTURE_SIZE, PROFILE_THUMBNAIL_SIZE, User

_MEDIA = tempfile.mkdtemp(prefix="pptest-")


def _heic(size=(1200, 900)):
    import pillow_heif

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 90, 160)).save(buf, format="HEIF")
    return buf.getvalue()


def _img(fmt, size, mode="RGB", color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return buf.getvalue()


@override_settings(MEDIA_ROOT=_MEDIA)
class ProfilePictureProcessingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def _make_user(self, filename, data, content_type):
        return User.objects.create_user(
            email="p@example.com",
            password="pw",
            first_name="P",
            last_name="Q",
            profile_picture=SimpleUploadedFile(filename, data, content_type=content_type),
        )

    def _open(self, fieldfile):
        fieldfile.open("rb")
        img = Image.open(io.BytesIO(fieldfile.read()))
        img.load()
        return img

    def test_heic_is_converted_to_jpeg_and_downscaled(self):
        user = self._make_user("selfie.heic", _heic((1200, 900)), "image/heic")
        self.assertTrue(user.profile_picture.name.endswith(".jpg"), user.profile_picture.name)
        main = self._open(user.profile_picture)
        self.assertEqual(main.format, "JPEG")
        self.assertLessEqual(max(main.size), max(PROFILE_PICTURE_SIZE))
        # thumbnail derived and small
        self.assertTrue(user.profile_picture_thumbnail.name)
        thumb = self._open(user.profile_picture_thumbnail)
        self.assertLessEqual(max(thumb.size), max(PROFILE_THUMBNAIL_SIZE))

    def test_large_jpeg_is_downscaled(self):
        user = self._make_user("big.jpg", _img("JPEG", (2000, 1500)), "image/jpeg")
        main = self._open(user.profile_picture)
        self.assertLessEqual(max(main.size), max(PROFILE_PICTURE_SIZE))
        self.assertEqual(main.size, (512, 384))

    def test_transparent_png_stays_png(self):
        user = self._make_user(
            "logo.png", _img("PNG", (800, 800), mode="RGBA", color=(0, 0, 0, 0)), "image/png"
        )
        self.assertTrue(user.profile_picture.name.endswith(".png"))
        self.assertEqual(self._open(user.profile_picture).format, "PNG")

    def test_small_picture_is_not_upscaled(self):
        user = self._make_user("tiny.jpg", _img("JPEG", (100, 80)), "image/jpeg")
        self.assertEqual(self._open(user.profile_picture).size, (100, 80))

    def test_api_path_also_processes_and_persists_thumbnail(self):
        # The profile API saves update_fields=['profile_picture']; the thumbnail
        # (and processed picture) must still persist.
        from usermodel.api import UpdateProfileSerializer

        user = User.objects.create_user(email="a@example.com", password="pw")
        ser = UpdateProfileSerializer()
        ser.update(
            user,
            {"profile_picture": SimpleUploadedFile("s.heic", _heic(), "image/heic")},
        )
        user.refresh_from_db()
        self.assertTrue(user.profile_picture.name.endswith(".jpg"))
        self.assertTrue(user.profile_picture_thumbnail.name)
