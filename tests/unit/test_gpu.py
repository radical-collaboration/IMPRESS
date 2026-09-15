import subprocess
from unittest.mock import patch

from impress.utils.gpu import find_gpus


def _completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


class TestFindGpusFromEnv:
    def test_parses_cuda_visible_devices(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "0,2,3"}):
            assert find_gpus() == [0, 2, 3]

    def test_env_path_does_not_shell_out(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "1"}):
            with patch("subprocess.run") as run:
                assert find_gpus() == [1]
                run.assert_not_called()

    def test_tolerates_whitespace(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": " 0 , 1 "}):
            assert find_gpus() == [0, 1]


class TestFindGpusFallsBackToNvidiaSmi:
    def test_empty_env_falls_through(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": ""}):
            with patch("subprocess.run", return_value=_completed("0\n1\n")) as run:
                assert find_gpus() == [0, 1]
                run.assert_called_once()

    def test_non_numeric_env_falls_through(self):
        # Devices may be named by UUID rather than index.
        uuid = "GPU-a1b2c3d4"
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": uuid}):
            with patch("subprocess.run", return_value=_completed("0\n1\n2\n")):
                assert find_gpus() == [0, 1, 2]

    def test_ignores_unparseable_output_lines(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": ""}):
            with patch("subprocess.run", return_value=_completed("0\n\nno_gpus\n1\n")):
                assert find_gpus() == [0, 1]


class TestFindGpusFallbackToEmpty:
    def test_nvidia_smi_missing(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": ""}):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                assert find_gpus() == []

    def test_nvidia_smi_times_out(self):
        exc = subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": ""}):
            with patch("subprocess.run", side_effect=exc):
                assert find_gpus() == []

    def test_nvidia_smi_nonzero_return(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": ""}):
            with patch("subprocess.run", return_value=_completed("", returncode=9)):
                assert find_gpus() == []

    def test_no_gpus_anywhere(self):
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": ""}):
            with patch("subprocess.run", return_value=_completed("")):
                assert find_gpus() == []
