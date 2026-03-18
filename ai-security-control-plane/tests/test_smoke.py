def test_package_importable():
    import ascp

    assert ascp.__version__ == "0.1.0"
