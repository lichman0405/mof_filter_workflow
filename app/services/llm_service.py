# mcp_service/app/services/llm_service.py
# The module is responsible for interacting with a Large Language Model (LLM) API using the official 'openai' library.
# It reads configuration from the global settings to determine which LLM provider to use and fetches
# the corresponding credentials.
# Author: Shibo Li
# Date: 2025-06-16 
# Version: 0.1.0


import json
from typing import Dict, Any
from openai import AsyncOpenAI, OpenAIError
from app.core.settings import settings
from app.utils.logger import logger

class LLMClient:
    """
    A client to interact with a Large Language Model API using the official 'openai' library.
    It reads configuration from the global settings to determine which
    LLM provider to use and fetches the corresponding credentials.
    """
    def __init__(self):
        """
        Initializes the client by creating an AsyncOpenAI instance configured
        for the selected provider.
        """
        self.provider = settings.LLM_PROVIDER.upper()
        logger.info(f"Initializing LLMClient with provider: {self.provider} using 'openai' library")

        provider_prefix = self.provider
        if "DEEPSEEK" in self.provider:
            provider_prefix = "DEEPSEEK_CHAT" if "CHAT" in self.provider else "DEEPSEEK_REASONER"
        
        try:
            api_key = getattr(settings, f"{provider_prefix}_API_KEY")
            base_url = getattr(settings, f"{provider_prefix}_BASE_URL")
            self.model = getattr(settings, f"{provider_prefix}_MODEL")

            if not all([api_key, base_url, self.model]):
                raise ValueError("One or more required settings (API_KEY, BASE_URL, MODEL) are missing for the selected provider.")

            # Create an instance of the AsyncOpenAI client
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )

        except (AttributeError, ValueError) as e:
            logger.error(f"Configuration error for LLM provider '{self.provider}': {e}")
            raise ValueError(f"Invalid or incomplete configuration for LLM provider: {self.provider}")

        # The system prompt remains crucial for instructing the LLM to return valid JSON.
        self.system_prompt = """
You are an expert materials science AI assistant. Your task is to convert a user's natural language request for screening MOF (Metal-Organic Framework) materials into a structured JSON object.

The user will provide criteria for properties like pore diameter, surface area, and channel dimensionality. You must parse these criteria and create a JSON object containing a list of rules.

The JSON object must have a single key "rules", which is a list. Each item in the list is a rule object with three keys:
1.  `metric`: A string representing the physical property. It must be one of the following exact values: "pore_diameter", "surface_area", "accessible_volume", "probe_volume", "channel_dimension".
2.  `condition`: A string representing the comparison operator. It must be one of: "greater_than", "less_than", "equals".
3.  `value`: A number (integer or float) representing the target value for the criterion.

Example:
User prompt: "I need materials with a pore diameter larger than 7 angstroms and a channel dimension that is 3D."
Your output MUST be ONLY the following JSON object and nothing else:
{
  "rules": [
    {
      "metric": "pore_diameter",
      "condition": "greater_than",
      "value": 7.0
    },
    {
      "metric": "channel_dimension",
      "condition": "equals",
      "value": 3
    }
  ]
}
"""

    async def get_structured_rules_from_prompt(self, user_prompt: str) -> Dict[str, Any]:
        """
        Sends the user's prompt to the configured LLM API using the 'openai' client
        and returns the structured JSON rules.
        """
        try:
            logger.info(f"Sending request to LLM provider '{self.provider}' with model '{self.model}'")
            
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                timeout=60.0
            )

            llm_response_text = completion.choices[0].message.content
            logger.success("Successfully received response from LLM.")
            
            parsed_json = json.loads(llm_response_text)
            logger.success("Successfully parsed LLM response into JSON.")
            return parsed_json

        except OpenAIError as e:
            logger.error(f"An OpenAI API error occurred: {e}")
            raise
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse or find content in LLM response: {e}")
            raise
