# Milestones

## **Step 1: Project Setup**
1. **Create Repository**:
   - Initialize a GitHub repo named `MyPropMate`.
   - Set up a basic folder structure:
     ```
     /backend
     /frontend
     /docs
     ```
2. **Backend Setup**:
   - Set up a Node.js + Express backend with TypeScript.
   - Install key dependencies:
     ```bash
     npm install express cors body-parser pdfkit nodemailer
     ```
   - Configure `tsconfig.json` for TypeScript.
   - Create an initial `server.ts` file to test a simple API endpoint.

3. **Frontend Setup**:
   - Initialize a React project with TypeScript.
   - Install dependencies:
     ```bash
     npm install axios react-router-dom
     ```
   - Set up a simple homepage for testing.

---

## **Step 2: Backend Receipt Logic**
1. **Define Receipt Data Model**:
   Create a `Receipt` model that includes:
   - Tenant name.
   - Property address.
   - Payment date.
   - Amount paid.
   - Receipt number.

2. **Generate PDF Receipts**:
   - Use `pdfkit` to dynamically generate receipts.
   - Define a receipt template with placeholders for tenant details.
   - Save the receipt as a file on the server or in-memory for download.

3. **Test API Endpoint**:
   - Create a POST endpoint (e.g., `/api/receipts`) that accepts JSON data (tenant info, payment details) and generates a PDF receipt.
   - Return the generated PDF as a downloadable file or a file path.

   Example API:
   ```typescript
   app.post('/api/receipts', async (req, res) => {
       const { tenantName, propertyAddress, paymentDate, amount, receiptNumber } = req.body;

       const doc = new PDFDocument();
       const fileName = `receipt_${receiptNumber}.pdf`;
       const filePath = `./receipts/${fileName}`;

       doc.pipe(fs.createWriteStream(filePath));
       doc.text(`Receipt Number: ${receiptNumber}`);
       doc.text(`Tenant Name: ${tenantName}`);
       doc.text(`Property Address: ${propertyAddress}`);
       doc.text(`Payment Date: ${paymentDate}`);
       doc.text(`Amount Paid: $${amount}`);
       doc.end();

       res.json({ message: 'Receipt generated', filePath });
   });
   ```

---

## **Step 3: Frontend Receipt Form**
1. **Create Receipt Form**:
   - Add a simple React form for entering tenant details and payment info.
   - Fields:
     - Tenant Name
     - Property Address
     - Payment Date
     - Amount
     - Receipt Number
   - Submit the form data to the backend endpoint.

2. **Display Generated Receipt**:
   - On form submission, display a link or button to download the generated receipt.

---

#### **Step 4: Testing**
- **Manual Testing**:
  - Use sample tenant and payment details to generate a receipt.
  - Download the PDF and confirm that the content matches the input data.
- **Iterative Improvements**:
  - Add validations to ensure required fields are filled.
  - Enhance the receipt template (e.g., logos, formatting).

---

### **Deliverable**
By completing this milestone, you’ll have a functional receipt generation feature that:
- Accepts tenant and payment details.
- Generates a downloadable PDF receipt.
- Can be tested in a real scenario with your tenant data.