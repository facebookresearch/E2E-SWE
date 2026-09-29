import pytest

from feeder import Feeder


@pytest.fixture()
def feeder():
    # setup
    f = Feeder()
    yield f
    # teardown
    f.stop()


@pytest.fixture()
def feeder_fd():
    # setup -- J1939-22 (CAN-FD) data link layer
    f = Feeder(data_link_layer="j1939-22")
    yield f
    # teardown
    f.stop()
