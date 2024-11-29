# Architecture

## System Architecture
The application will be a modular web-based solution that leverages modern tools for scalability and maintainability. The tech stack has been chosen to support an efficient development workflow and a smooth learning curve, particularly with TypeScript for type safety and reliability.

### Tech Stack
- **Frontend**: 
  - **React with TypeScript**: For building a responsive, type-safe, and dynamic user interface.
  - **React Query or Redux Toolkit**: For state management and API interaction.
  - **CSS Framework**: TailwindCSS or Material-UI for styling and UI components.
- **Backend**:
  - **Node.js with Express**: For building REST APIs.
  - **TypeScript**: To bring type safety and consistency to backend development.
- **Database**:
  - **PostgreSQL**: A relational database for managing structured data.
  - **Prisma ORM (Optional)**: To simplify database interaction using TypeScript.
- **Authentication**:
  - JSON Web Tokens (JWT) for secure user sessions.
  - Optional: OAuth 2.0 or social logins in later phases.
- **Email Service**: Integration with services like SendGrid for automated emails.
- **Hosting**: Cloud platform (e.g., AWS, Azure, or Vercel for the frontend).

---

## Database Design
The database schema will follow a relational design, structured as follows:

### Tables
1. **Users**:
    - `id` (Primary Key)
    - `name`
    - `email`
    - `password_hash`
    - `role` (e.g., "Landlord", "Manager")
    - `created_at`, `updated_at`

2. **Properties**:
    - `id` (Primary Key)
    - `user_id` (Foreign Key to Users)
    - `address`
    - `description`
    - `value`
    - `created_at`, `updated_at`

3. **Tenants**:
    - `id` (Primary Key)
    - `property_id` (Foreign Key to Properties)
    - `name`
    - `email`
    - `phone`
    - `lease_start_date`
    - `lease_end_date`
    - `created_at`, `updated_at`

4. **Payments**:
    - `id` (Primary Key)
    - `tenant_id` (Foreign Key to Tenants)
    - `amount`
    - `payment_date`
    - `status` (e.g., "Paid", "Pending", "Overdue")
    - `receipt_id` (Link to generated receipts)
    - `created_at`, `updated_at`

5. **Receipts**:
    - `id` (Primary Key)
    - `payment_id` (Foreign Key to Payments)
    - `receipt_number`
    - `file_path` (Path to PDF storage)
    - `email_sent` (Boolean flag)
    - `created_at`, `updated_at`

6. **Maintenance Requests** (Future Feature):
    - `id` (Primary Key)
    - `property_id` (Foreign Key to Properties)
    - `description`
    - `status` (e.g., "Open", "In Progress", "Resolved")
    - `submitted_by` (e.g., Tenant ID or Landlord ID)
    - `created_at`, `updated_at`

---

## Application Flow
1. **User Authentication**: 
   - Secure login system using JWT.
   - Role-based access (e.g., landlords managing properties, property managers with delegated access).
2. **Property Management**:
   - Add, edit, and delete property details.
   - Assign tenants to properties.
3. **Rent Tracking**:
   - Record rent payments, update statuses, and view payment history.
4. **Receipt Generation**:
   - Automatically generate PDFs for rent payments.
   - Send receipts to tenants via email.
5. **Dashboard**:
   - A centralized interface showing rent collection metrics, overdue payments, and property statuses.

---

## Component Breakdown
### Frontend
- **Login/Sign-Up**: Secure, type-safe forms.
- **Dashboard**: Overview of properties, tenants, payments, and alerts.
- **Receipt Generator**: User interface to generate and view payment receipts.
- **Tenant Manager**: CRUD operations for tenant data.
- **Property Manager**: Manage property details, track rents, and assign tenants.

### Backend
- **REST API Endpoints**:
  - `POST /login`: Authenticate users.
  - `GET /properties`: Retrieve user properties.
  - `POST /payments`: Record a payment and generate receipts.
- **Services**:
  - **Email Service**: For sending receipts and notifications.
  - **Database Service**: Type-safe ORM queries using Prisma.

---

## Component Diagram
A PlantUML diagram of the system components:

```plantuml
@startuml
actor User
actor Tenant

rectangle Frontend {
    component "React + TypeScript App" as WebApp
}

rectangle Backend {
    component "API Service (Express + TypeScript)" as API
    component "Database (PostgreSQL)" as DB
    component "Email Service" as Email
}

User --> WebApp
Tenant --> WebApp
WebApp --> API
API --> DB
API --> Email
@enduml
