from app.processors.image_processor import ImageProcessor


def test_extract_exif_reads_public_exif_ifd_without_private_jpeg_api():
    class ExifData(dict):
        def get_ifd(self, ifd):
            if ifd == 34665:
                return {36867: "2020:05:04 12:30:00", 271: "Example Camera"}
            if ifd == 34853:
                return {}
            return {}

    processor = ImageProcessor()

    class Image:
        info = {}

        def getexif(self):
            return ExifData()

    image = Image()

    exif = processor._extract_exif(image)

    assert exif["DateTimeOriginal"] == "2020:05:04 12:30:00"
    assert exif["Make"] == "Example Camera"
