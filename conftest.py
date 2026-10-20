"""Datos sintéticos (DICOM, STL, PNG) y entorno offscreen para las pruebas de Vissium."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest


def _make_series(folder, n=12, desc="Serie"):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

    os.makedirs(folder, exist_ok=True)
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    zz, yy, xx = np.mgrid[0:n, 0:64, 0:64]
    vol = (((xx - 32) ** 2 + (yy - 32) ** 2 + (zz - n / 2) ** 2 * 4) < 600).astype(np.uint16) * 1500 + 100
    for i in range(n):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        sop = generate_uid()
        meta.MediaStorageSOPInstanceUID = sop
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, sop
        ds.PatientName, ds.PatientID = "PRUEBA^PACIENTE", "P001"
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.Modality, ds.SeriesNumber, ds.InstanceNumber = "CT", 1, i + 1
        ds.SeriesDescription, ds.StudyDate = desc, "20261001"
        ds.Rows = ds.Columns = 64
        ds.PixelSpacing, ds.SliceThickness = [0.3, 0.3], 0.3
        ds.ImagePositionPatient = [0, 0, i * 0.3]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, 0
        ds.RescaleIntercept, ds.RescaleSlope = -1000, 1
        ds.PixelData = vol[i].tobytes()
        ds.save_as(os.path.join(folder, f"IM{i:04d}.dcm"), enforce_file_format=True)


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    from PIL import Image

    root = tmp_path_factory.mktemp("fx")
    _make_series(str(root / "dicom_flat"), 12, "Serie unica")
    _make_series(str(root / "cd" / "DICOM" / "PAT" / "SER1"), 10, "Serie A")
    _make_series(str(root / "cd" / "DICOM" / "PAT" / "SER2"), 12, "Serie B")
    (root / "modelo.stl").write_text(
        "solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\n"
        "vertex 0 1 0\nendloop\nendfacet\nendsolid t\n")
    Image.fromarray((np.random.rand(60, 90, 3) * 255).astype("uint8")).save(root / "foto.png")
    return root
