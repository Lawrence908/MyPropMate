from openpyxl import load_workbook

# Load the Excel template
template_path = 'Rental Receipt - Neumann.xlsx'  # Update with your local path
workbook = load_workbook(template_path)
sheet = workbook['Simple Receipt (light)']

# Example dynamic data for the receipt
dynamic_data = {
    "invoice_number": 15,  # Incremented value
    "owner_name": "Chris Lawrence",
    "property_address": "1030 10A St",
    "property_location": "Wainwright, AB T9W 1B7",
    "property_phone": "(780) 937-6367",
    "payment_date": "2024-11-01",
    "tenant_name": "John Doe",
    "tenant_phone": "(780) 123-4567",
    "rental_charge": 1200,
    "parking_charge": 150,
    "description": "November 2024 Rental Charge"
}

# Update the cells with dynamic data
sheet['C4'] = dynamic_data['invoice_number']
sheet['C6'] = dynamic_data['owner_name']
sheet['C7'] = dynamic_data['property_address']
sheet['C8'] = dynamic_data['property_location']
sheet['C9'] = dynamic_data['property_phone']

sheet['H4'] = dynamic_data['payment_date']
sheet['H7'] = dynamic_data['tenant_name']
sheet['H8'] = dynamic_data['tenant_phone']

sheet['H13'] = dynamic_data['rental_charge']
sheet['H14'] = dynamic_data['parking_charge']

sheet['B13'] = dynamic_data['description']

# Save the updated Excel file
output_path = 'Updated_Rental_Receipt.xlsx'
workbook.save(output_path)

print(f"Receipt saved to {output_path}")
