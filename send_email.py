import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class SimpleEmailSender:
    """
    A simple class to send emails using Gmail SMTP with credentials from environment variables
    """
    def __init__(self):
        # Setup logger
        self.logger = logging.getLogger('EmailSender')
        
        # Get credentials from environment variables
        self.smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.from_email = os.environ.get('SMTP_USERNAME')  # Gmail address
        self.password = os.environ.get('SMTP_PASSWORD')    # Gmail password
        self.from_name = os.environ.get('FROM_NAME', 'VoucherVision API')
        
        # Check if email sending is enabled
        self.is_enabled = all([
            self.smtp_server,
            self.smtp_port,
            self.from_email,
            self.password
        ])
        
        if not self.is_enabled:
            self.logger.warning("Email sending is disabled due to missing configuration")
            missing = []
            if not self.smtp_server: missing.append('SMTP_SERVER')
            if not self.smtp_port: missing.append('SMTP_PORT')
            if not self.from_email: missing.append('SMTP_USERNAME')
            if not self.password: missing.append('SMTP_PASSWORD')
            if missing:
                self.logger.warning(f"Missing environment variables: {', '.join(missing)}")
    
    def send_email(self, to_email, subject, body):
        """
        Send a simple email
        
        Args:
            to_email (str): Recipient email address
            subject (str): Email subject
            body (str): Email body (HTML or plain text)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_enabled:
            self.logger.warning(f"Email not sent to {to_email}: Email sending is disabled")
            return False
        
        try:
            # Create a multipart message
            msg = MIMEMultipart()
            msg['From'] = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Determine if body is HTML or plain text
            if body.strip().startswith('<'):
                # Looks like HTML
                msg.attach(MIMEText(body, 'html'))
            else:
                # Plain text
                msg.attach(MIMEText(body, 'plain'))
            
            # Connect to the SMTP server and send the email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(self.from_email, self.password)
                server.send_message(msg)
            
            self.logger.info(f"Email sent to {to_email}: {subject}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def send_approval_notification(self, user_email):
        """
        Send application approval notification email
        
        Args:
            user_email (str): The recipient's email address
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        subject = "Your VoucherVision API Application has been Approved"
        
        # Create HTML content
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4285f4;">Application Approved</h2>
                    <p>Dear {user_email},</p>
                    <p>We're pleased to inform you that your application for access to the VoucherVision API has been approved.</p>
                    <p>You can now log in to your account and access the API through our web interface or via API tokens.</p>
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vouchervision-go-738307415303.us-central1.run.app/auth-success" 
                           style="background-color: #4285f4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                            Access Your Account
                        </a>
                    </div>
                    <p>If you have any questions or need assistance, please don't hesitate to contact us.</p>
                    <p>Thank you for your interest in VoucherVision!</p>
                    <p>Best regards,<br>The VoucherVision Team</p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body)
    
    def send_api_key_permission_notification(self, user_email):
        """
        Send API key permission granted notification email
        
        Args:
            user_email (str): The recipient's email address
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        subject = "API Key Access Granted for VoucherVision"
        
        # Create HTML content
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4285f4;">API Key Access Granted</h2>
                    <p>Dear {user_email},</p>
                    <p>We're pleased to inform you that you have been granted permission to create API keys for programmatic access to the VoucherVision API.</p>
                    <p>API keys allow your applications to authenticate with our API without browser-based authentication, enabling automated workflows and integrations.</p>
                    <div style="margin: 30px 0; text-align: center;">
                        <a href="https://vouchervision-go-738307415303.us-central1.run.app/api-key-management" 
                           style="background-color: #4285f4; color: white; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                            Manage Your API Keys
                        </a>
                    </div>
                    <p>Please remember to keep your API keys secure and never share them publicly. You can revoke and manage your keys at any time through the API Key Management page.</p>
                    <p>If you have any questions about using API keys or need technical assistance, please contact us.</p>
                    <p>Best regards,<br>The VoucherVision Team</p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body)