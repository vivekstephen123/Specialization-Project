import os
import json
import re
from typing import List, Dict, Any
import google.generativeai as genai
from PIL import Image

class BillItemExtractor:
    def __init__(self, api_key: str):
        """
        Initialize the Bill Item Extractor with Gemini API key.

        Args:
            api_key (str): Google Gemini API key
        """
        self.api_key = api_key
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def extract_items_from_bill(self, image_path: str) -> List[Dict[str, Any]]:
        """
        Extract items from bill image using Gemini API.

        Args:
            image_path (str): Path to the bill image

        Returns:
            List[Dict]: List of extracted items with quantities
        """
        try:
            # Load and process the image
            image = Image.open(image_path)

            # Create the prompt for Gemini
            prompt = """
            Extract each item purchased from this bill image, along with its numerical quantity and the unit of measurement (e.g., 'kg', 'g', 'ml', 'liter', 'pcs', 'dozen', 'packet', 'loaf', 'lb').

            IMPORTANT INSTRUCTIONS:
            1. Strip away ALL brand names, company names, and descriptive adjectives from item names
            2. Keep only the core/generic item name (e.g., "California Crispy Apples" → "Apple", "Coca Cola" → "Cola", "Organic Free Range Eggs" → "Egg")
            3. Use singular form for item names (e.g., "Apples" → "Apple", "Potatoes" → "Potato")
            4. If a unit is not explicitly stated but a number is present, assume 'pcs' (pieces) as the default unit
            5. Ignore prices, dates, store names, tax information, or other irrelevant information
            6. Focus only on the items purchased and their quantities

            Provide the output as a clean JSON array of objects, where each object has the following structure:
            {
              "item_name": "string (generic item name without brands/adjectives, singular form)",
              "quantity_value": number,
              "quantity_unit": "string (unit like kg, g, ml, liter, pcs, dozen, packet, loaf, lb)"
            }

            Example transformations:
            - "California Crispy Apples" → "Apple"
            - "Organic Free Range Eggs" → "Egg"
            - "Coca Cola 500ml" → "Cola"
            - "Wonder Bread Whole Wheat" → "Bread"
            - "Dole Bananas" → "Banana"
            - "Roma Tomatoes" → "Tomato"
            - "Red Onions" → "Onion"

            Example output:
            [
              {"item_name": "Potato", "quantity_value": 2, "quantity_unit": "kg"},
              {"item_name": "Egg", "quantity_value": 12, "quantity_unit": "pcs"},
              {"item_name": "Milk", "quantity_value": 1, "quantity_unit": "liter"}
            ]
            """

            # Generate content using Gemini
            response = self.model.generate_content([prompt, image])

            # Extract and clean the JSON response
            response_text = response.text.strip()

            # Remove markdown code blocks if present
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)
            else:
                # Try to find JSON array directly
                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    json_text = json_match.group(0)
                else:
                    json_text = response_text

            # Parse JSON
            try:
                extracted_items = json.loads(json_text)
                return extracted_items if isinstance(extracted_items, list) else []
            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {e}")
                print(f"Response text: {response_text}")
                return []

        except Exception as e:
            print(f"Error extracting items from bill: {str(e)}")
            return []

    def create_json_output(self, extracted_items: List[Dict[str, Any]]) -> str:
        """
        Create clean JSON output from extracted items.

        Args:
            extracted_items (List[Dict]): List of extracted items

        Returns:
            str: JSON string of the results
        """
        if not extracted_items:
            return json.dumps({
                "success": False,
                "message": "No items could be extracted from the bill image",
                "items": [],
                "total_items": 0
            }, indent=2)

        # Create clean output structure
        output = {
            "success": True,
            "message": f"Successfully extracted {len(extracted_items)} items",
            "items": [],
            "total_items": len(extracted_items)
        }

        # Process each item for clean JSON output
        for item in extracted_items:
            clean_item = {
                "name": item.get('item_name', 'Unknown Item'),
                "quantity": {
                    "value": item.get('quantity_value', 0),
                    "unit": item.get('quantity_unit', 'pcs')
                },
                "quantity_display": f"{item.get('quantity_value', 0)} {item.get('quantity_unit', 'pcs')}"
            }
            output['items'].append(clean_item)

        return json.dumps(output, indent=2)

    def extract_and_format(self, image_path: str) -> str:
        """
        Main function that extracts items from bill and returns formatted JSON output.
        This function calls both extract_items_from_bill and create_json_output.

        Args:
            image_path (str): Path to the bill image

        Returns:
            str: JSON string of the extraction results
        """
        print(f"Processing bill image: {image_path}")

        # Step 1: Extract items from bill
        print("Extracting items from bill...")
        extracted_items = self.extract_items_from_bill(image_path)

        # Step 2: Create JSON output
        print("Creating JSON output...")
        json_output = self.create_json_output(extracted_items)

        print(f"Extraction complete! Found {len(extracted_items)} items.")
        return json_output

    def save_json_to_file(self, json_output: str, output_file: str) -> bool:
        """
        Save JSON output to a file.

        Args:
            json_output (str): JSON string to save
            output_file (str): Path to save the JSON file

        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(json_output)
            print(f"✅ Results saved to: {output_file}")
            return True
        except Exception as e:
            print(f"❌ Error saving JSON output: {str(e)}")
            return False


# Example function to process the JSON output
def process_bill_json(json_file_path: str) -> Dict[str, Any]:
    """
    Example function showing how to process the saved JSON output.

    Args:
        json_file_path (str): Path to the JSON file

    Returns:
        Dict: Processed data for further use
    """
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data['success']:
            return {"error": data['message']}

        # Example processing - create a shopping list
        shopping_list = []

        for item in data['items']:
            shopping_list.append({
                'name': item['name'],
                'quantity_value': item['quantity']['value'],
                'quantity_unit': item['quantity']['unit'],
                'display': item['quantity_display']
            })

        return {
            'success': True,
            'shopping_list': shopping_list,
            'total_items': len(shopping_list)
        }

    except Exception as e:
        return {"error": f"Failed to process JSON: {str(e)}"}