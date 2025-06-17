# mcp_service/app/services/worker_clients.py

import httpx
import os
from typing import Dict, Any
from app.core.settings import settings
from app.utils.logger import logger

class ZeoClient:
    """
    A client for interacting with the Zeo++ microservice.
    This version is complete and calls all six specified analysis endpoints.
    """
    def __init__(self, task_storage_path: str = None):
        """
        Initializes the ZeoClient with the base URL from settings and an optional storage path for task results.
        Args:
            task_storage_path: Optional path where results can be stored. If provided, it will be used to save files like pore size distribution.
        If not provided, file downloads will be skipped. 
        """
        self.base_url = settings.ZEO_API_BASE_URL
        self.task_storage_path = task_storage_path


    async def get_all_properties(self, cif_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Calls all relevant endpoints of the Zeo++ service for a given CIF file
        and aggregates the results into a single dictionary.

        Args:
            cif_content: The content of the .cif file as bytes.
            filename: The original name of the file, used for saving derivatives.

        Returns:
            A dictionary containing all calculated properties.
        """
        all_results = {}
        default_params = {
            "probe_radius": 1.2, # e.g., for N2 probe
            "chan_radius": 1.2,
            "samples": 2000 # A reasonable number of samples
        }
        
        # Define the endpoints to call, including the missing 'probe_volume' endpoint
        endpoints_to_call = [
            ("pore_diameter", "/pore_diameter", {"-ha": "true"}),
            ("surface_area", "/surface_area", default_params),
            ("accessible_volume", "/accessible_volume", default_params),
            ("probe_volume", "/probe_volume", default_params),
            ("channel_analysis", "/channel_analysis", {"probe_radius": default_params["probe_radius"]}),
        ]

        async with httpx.AsyncClient(base_url=self.base_url, timeout=300.0) as client:
            for key, path, params in endpoints_to_call:
                files = {'structure_file': (filename, cif_content, 'application/octet-stream')}
                try:
                    logger.info(f"Calling Zeo++ endpoint: {path}")
                    response = await client.post(path, files=files, data=params)
                    response.raise_for_status()
                    all_results[key] = response.json()
                    logger.success(f"Successfully got '{key}' from Zeo++.")
                except httpx.HTTPStatusError as e:
                    error_msg = f"Zeo++ API for '{key}' failed with status {e.response.status_code}: {e.response.text}"
                    logger.error(error_msg)
                    all_results[key] = {"error": error_msg}
                except Exception as e:
                    logger.error(f"An unexpected error occurred while calling '{key}': {e}")
                    all_results[key] = {"error": str(e)}

            if self.task_storage_path:
                psd_path = "/pore_size_dist/download"
                psd_params = { "probe_radius": 1.2, "chan_radius": 1.86, "samples": default_params["samples"]}
                files = {'structure_file': (filename, cif_content, 'application/octet-stream')}
                try:
                    logger.info(f"Calling Zeo++ endpoint for file download: {psd_path}")
                    response = await client.post(psd_path, files=files, data=psd_params)
                    response.raise_for_status()
                    
                    output_filename = f"{os.path.splitext(filename)[0]}_psd.txt"
                    output_path = os.path.join(self.task_storage_path, output_filename)
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    
                    all_results['pore_size_distribution_file'] = output_path
                    logger.success(f"Successfully downloaded and saved pore size distribution to: {output_path}")

                except httpx.HTTPStatusError as e:
                    error_msg = f"Zeo++ PSD download failed with status {e.response.status_code}: {e.response.text}"
                    logger.error(error_msg)
                    all_results['pore_size_distribution_file'] = {"error": error_msg}
            else:
                logger.warning("task_storage_path not provided to ZeoClient, skipping file download.")

        return all_results

class FileConverterClient:
    """
    A client for the file type conversion microservice.
    """
    def __init__(self):
        self.base_url = settings.CONVERTER_API_BASE_URL

    async def convert_file(self, file_content: bytes, source_filename: str) -> bytes:
        endpoint = f"{self.base_url}/convert/"
        files = {'file': (source_filename, file_content, 'application/octet-stream')}
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Calling File Converter: {source_filename}")
                response = await client.post(endpoint, files=files, timeout=120.0)
                response.raise_for_status()
                logger.success(f"Successfully converted file.")
                return response.content
            except httpx.HTTPStatusError as e:
                error_msg = f"File conversion failed with status {e.response.status_code}: {e.response.text}"
                logger.error(error_msg)
                raise ValueError(error_msg)


class MaceClient:
    """
    A client for the MACE optimization microservice.
    """
    def __init__(self):
        self.base_url = settings.MACE_API_BASE_URL

    async def optimize_structure(self, xyz_content: bytes) -> bytes:
        optimize_endpoint = f"{self.base_url}/optimize"
        files = {'structure_file': ('structure.xyz', xyz_content, 'application/octet-stream')}
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Calling MACE endpoint: {optimize_endpoint}")
                response_opt = await client.post(optimize_endpoint, files=files, timeout=600.0)
                response_opt.raise_for_status()
                opt_results = response_opt.json()
                logger.success("MACE optimization job completed.")

                download_path = opt_results.get("download_links", {}).get("xyz")
                if not download_path:
                    raise ValueError("No XYZ download link found in MACE response.")
                
                download_url = f"{self.base_url}{download_path}"
                logger.info(f"Downloading optimized structure from: {download_url}")
                response_dl = await client.get(download_url, timeout=120.0)
                response_dl.raise_for_status()
                logger.success("Successfully downloaded optimized XYZ file.")
                
                return response_dl.content

            except httpx.HTTPStatusError as e:
                error_msg = f"MACE API request failed with status {e.response.status_code}: {e.response.text}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            

class XTBClient:
    """
    A new client for the final XTB optimization microservice.
    """
    def __init__(self):
        self.base_url = settings.XTB_API_BASE_URL

    async def optimize_structure(self, xyz_content: bytes, charge: int = 0, uhf: int = 0, gfn: int = 2) -> bytes:
        """
        Calls the XTB optimization service. Based on your description,
        it takes a file and parameters, and returns the optimized file directly.

        Args:
            xyz_content: The content of the .xyz file.
            charge: The charge of the system.
            uhf: The number of unpaired electrons.
            gfn: The GFN-xTB version to use (0, 1, or 2).

        Returns:
            The content of the final optimized file as bytes.
        """
        endpoint = f"{self.base_url}/optimize"
        files = {'file': ('structure.xyz', xyz_content, 'application/octet-stream')}
        params = {'charge': charge, 'uhf': uhf, 'gfn': gfn}
        
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Calling XTB endpoint: {endpoint} with params: {params}")
                # The timeout for this final step should be generous.
                response = await client.post(endpoint, files=files, data=params, timeout=3600.0) # e.g., 1 hour timeout
                response.raise_for_status()
                logger.success("XTB optimization completed successfully.")
                return response.content
            except httpx.HTTPStatusError as e:
                error_msg = f"XTB optimization failed with status {e.response.status_code}: {e.response.text}"
                logger.error(error_msg)
                raise ValueError(error_msg)