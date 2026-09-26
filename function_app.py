import json
import logging
import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage  # NEW: For embedding images
from email.header import Header
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo
import base64  
import requests

import azure.functions as func
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import smtplib

# Templates (assuming these are in separate modules/files)
from templates.git_template import generate_github_style_html
from EvalTemplates.eval_standard import build_eval_st_template, _format_timestamp
from EvalTemplates.eval_standard import build_no_submission_template

# -----------------------------------------------------------------------------
# Azure Function App initialization
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
app: func.FunctionApp = func.FunctionApp()

# Cache environment variables for performance and consistency
try:
    MONGODB_URI = os.environ["MONGODB_URI"]
    MONGODB_DB = os.environ["MONGODB_DB"]
    MONGODB_DB_DEV = os.environ["MONGODB_DB_DEV"]
    SMTP_HOST = os.environ["SMTP_HOST"]
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
    SMTP_USER = os.environ["SMTP_USER"]
    SMTP_PASS = os.environ["SMTP_PASS"]
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    # Additional configurable values
    DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://mydsabuddy.com/dashboard/")
    WHATSAPP_COMMUNITY_LINK = os.environ.get("WHATSAPP_COMMUNITY_LINK", "https://chat.whatsapp.com/yourcommunitylink")
    LOGO_URL = os.environ.get("LOGO_URL", "https://res.cloudinary.com/diusbrwxl/image/upload/v1754248506/mdsabuddy-favicon_qbmven.png")
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@mydsabuddy.com")
    FEEDBACK_EMAIL = os.environ.get("FEEDBACK_EMAIL", "feedback@mydsabuddy.com")
    INSTAGRAM_URL = os.environ.get("INSTAGRAM_URL", "https://instagram.com/mydsabuddy")
    X_URL = os.environ.get("X_URL", "https://x.com/mydsabuddy")
    LINKEDIN_URL = os.environ.get("LINKEDIN_URL", "https://linkedin.com/company/mydsabuddy")
    HEADER_IMG = os.environ.get("HEADER_IMG", "https://res.cloudinary.com/diusbrwxl/image/upload/v1754377993/career_ladder_irn3fr.png")
    HEADER_LOGO = os.environ.get("HEADER_LOGO", "https://res.cloudinary.com/diusbrwxl/image/upload/v1754248506/my-dsa-buddy-white_rs9a6m.png")
    #additionalicons
    ICON_WP = os.environ.get("ICON_WP")  # WhatsApp icon next steps
    ICON_LINKEDIN = os.environ.get("ICON_LINKEDIN") # linkedin icon footer
    ICON_INSTA = os.environ.get("ICON_INSTA") #insta icon footer
    ICON_SHINE = os.environ.get("ICON_SHINE") #shine icon footer
    ICON_X = os.environ.get("ICON_X") #X icon footer
    ICON_HAND = os.environ.get("ICON_HAND")  # Robotic hand icon AI analysis how we help you succeed
    ICON_STAIRS = os.environ.get("ICON_STAIRS")  # Career ladder icon Header
    ICON_LOVE = os.environ.get("ICON_LOVE") #heart icon footer
    ICON_BOOK = os.environ.get("ICON_BOOK") #book icon our story
    ICON_HELP = os.environ.get("ICON_HELP")  # how we help you succeed icon
    ICON_CURATOR = os.environ.get("ICON_CURATOR") # Daily curation icon how we help you succeed
    ICON_LOOP = os.environ.get("ICON_LOOP")  # Smart Feedback icon how we help you succeed
    ICON_SUCCESS = os.environ.get("ICON_SUCCESS") #Progress Tracking icon how we help you succeed
    ICON_CAREER = os.environ.get("ICON_CAREER") #header icon
except KeyError as exc:
    logger.critical("Missing environment variable: %s", exc)
    raise RuntimeError(f"Missing environment variable: {exc}")

# -----------------------------------------------------------------------------
# Database helpers
# -----------------------------------------------------------------------------
def get_mongo_collection(collection_name: str, env: Optional[str] = None):
    """Return a handle to *collection_name* inside the database configured via env-vars."""
    try:
        db_name = MONGODB_DB_DEV if env == 'dev' else MONGODB_DB
        logger.info("MongoDB env: %s", db_name)
        client = MongoClient(MONGODB_URI)
        return client[db_name][collection_name]
    except PyMongoError as exc:
        logger.error("MongoDB connection error: %s", exc)
        raise

# -----------------------------------------------------------------------------
# SMTP helpers
# -----------------------------------------------------------------------------
def _get_smtp_config() -> Dict[str, Any]:
    return {
        "host": SMTP_HOST,
        "port": SMTP_PORT,
        "username": SMTP_USER,
        "password": SMTP_PASS,
        "use_tls": SMTP_USE_TLS,
    }


def send_email(smtp_config: Dict[str, Any], recipient: str, subject: str, body_html: str) -> None:
    msg = MIMEMultipart('alternative')
    msg['From'] = smtp_config['username']
    msg['To'] = recipient
    msg['Subject'] = Header(subject, 'utf-8')

    # Attach HTML
    msg.attach(MIMEText(body_html, 'html'))

    try:
        logger.info(f"Connecting to SMTP server {smtp_config['host']}:{smtp_config['port']}")
        if smtp_config['port'] == 465:
            with smtplib.SMTP_SSL(smtp_config['host'], smtp_config['port'], timeout=10) as server:
                if smtp_config['username'] and smtp_config['password']:
                    logger.info("Logging into SMTP server")
                    server.login(smtp_config['username'], smtp_config['password'])
                logger.info(f"Sending email to {recipient}")
                server.send_message(msg)
                logger.info(f"Email sent to {recipient} via SMTP_SSL.")
        else:
            with smtplib.SMTP(smtp_config['host'], smtp_config['port'], timeout=10) as server:
                if smtp_config['use_tls']:
                    logger.info("Starting TLS")
                    server.starttls()
                if smtp_config['username'] and smtp_config['password']:
                    logger.info("Logging into SMTP server")
                    server.login(smtp_config['username'], smtp_config['password'])
                logger.info(f"Sending email to {recipient}")
                server.send_message(msg)
                logger.info(f"Email sent to {recipient} via SMTP.")
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email to {recipient}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error sending email to {recipient}: {str(e)}")
        raise

# -----------------------------------------------------------------------------
# Welcome-email generation (enhanced with additional user insights)
# -----------------------------------------------------------------------------
def generate_welcome_email(user_data: Dict[str, Any]) -> str:
    # -- Stats --
    name = user_data.get("userId", "User")
    total_solved = user_data.get("totalProblemsSolved", 0)
    success_rate = user_data.get("overallSuccessRate", 0.0)
    average_attempts = user_data.get("averageAttemptsPerQuestion", 0.0)
    submit_stats = user_data.get("submitStats", [])
    easy_count = next((x.get("count", 0) for x in submit_stats if x.get("difficulty") == "Easy"), 0)
    medium_count = next((x.get("count", 0) for x in submit_stats if x.get("difficulty") == "Medium"), 0)
    hard_count = next((x.get("count", 0) for x in submit_stats if x.get("difficulty") == "Hard"), 0)
    topics = user_data.get("topics", {})
    strong_areas = ', '.join(
        t.replace('-', ' ').title() for t, v in topics.items() if v.get("strength") == "Strong"
    ) or "Not yet – Keep building!"
    weak_areas = ', '.join(
        t.replace('-', ' ').title() for t, v in topics.items() if v.get("strength") == "Weak"
    ) + " (We've got resources!)" if topics else "None"

    # -- Links --
    dashboard_url = DASHBOARD_URL
    support_email = SUPPORT_EMAIL
    feedback_email = FEEDBACK_EMAIL
    whatsapp_url = WHATSAPP_COMMUNITY_LINK
    header_logo = HEADER_LOGO
    header_image_url = HEADER_IMG
    logo_url = LOGO_URL  # Fallback if LOGO_URL is not set
    dashboard_link = dashboard_url  # For the "Track your progress" link
    # additional icons
    icon_wp = ICON_WP
    icon_linkedin = ICON_LINKEDIN
    icon_insta = ICON_INSTA
    icon_shine = ICON_SHINE
    icon_x = ICON_X
    icon_hand = ICON_HAND
    icon_stairs = ICON_STAIRS
    icon_love = ICON_LOVE
    icon_book = ICON_BOOK
    icon_help = ICON_HELP
    icon_curator = ICON_CURATOR
    icon_loop = ICON_LOOP
    icon_success = ICON_SUCCESS
    icon_career = ICON_CAREER

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome Email</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
      <style type="text/css">
        /* Client-specific styles */
        body {{
          margin: 0;
          padding: 0;
          -webkit-text-size-adjust: 100%;
          -ms-text-size-adjust: 100%;
        }}
        
        table {{
          border-collapse: collapse;
          mso-table-lspace: 0pt;
          mso-table-rspace: 0pt;
        }}
        
        img {{
          border: 0;
          height: auto;
          line-height: 100%;
          outline: none;
          text-decoration: none;
          -ms-interpolation-mode: bicubic;
        }}
        
        /* Responsive styles for mobile devices (max-width: 680px) */
        /* Dark mode logo inversion */

        @media (prefers-color-scheme: dark){{
          .dark-logo{{
          filter: brightness(0) invert(1) !important;
          }}
          }}
        @media only screen and (max-width: 680px) {{
          .main-table {{
            width: 100% !important;
            min-width: 100% !important;
          }}

          .mobile-padding {{
            padding: 15px !important;
          }}
          
          .mobile-text {{
            font-size: 14px !important;
            line-height: 20px !important;
          }}
          
          .mobile-heading {{
            font-size: 20px !important;
          }}
          
          .mobile-subheading {{
            font-size: 16px !important;
          }}
          
          .mobile-hide {{
            display: none !important;
          }}
          
          .mobile-full-width {{
            width: 100% !important;
            display: block !important;
          }}
          
          .button-container {{
            display: block !important;
            width: 100% !important;
          }}
          
          .button-cell {{
            display: block !important;
            width: 100% !important;
            padding: 8px 0 !important;
          }}
          
          .responsive-button {{
            width: 90% !important;
            max-width: 300px !important;
            padding: 12px 20px !important;
            font-size: 14px !important;
            display: block !important;
            margin: 0 auto !important;
          }}
          
          .icon-grid-cell {{
            width: 100% !important;
            display: block !important;
            padding: 10px !important;
          }}
          
          .stats-table {{
            font-size: 14px !important;
          }}
          
          .stats-table th,
          .stats-table td {{
            padding: 8px 5px !important;
          }}
          
          .header-logo {{
            width: 40px !important;
          }}
          
          .header-image {{
            width: 150px !important;
          }}
          
          .icon-large {{
            width: 60px !important;
            height: 60px !important;
          }}
          
          .icon-small {{
            width: 25px !important;
          }}
          
          .social-icon {{
            width: 28px !important;
            height: 28px !important;
          }}
          .mobile-show {{
            display: block !important;
          }}
          .spacer-height {{
            height: 10px !important;
          }}
        }}
        
        /* Responsive styles for tablet devices (681px - 1024px) */
        @media only screen and (min-width: 681px) and (max-width: 1024px) {{
          .main-table {{
            width: 100% !important;
            max-width: 680px !important;
          }}
          
          .tablet-padding {{
            padding: 18px !important;
          }}
          
          .icon-grid-cell {{
            width: 50% !important;
          }}
        }}
        
        /* Desktop styles (min-width: 1025px) */
        @media only screen and (min-width: 1025px) {{
          .main-table {{
            width: 680px !important;
          }}
        }}
      </style>
</head>

<body style="margin:0; padding:0; background:#fafafa; font-family:'Inter',Arial,Helvetica,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" border="0" align="center" class="main-table"
    style="max-width:680px;width:100%;margin:auto;border-collapse:collapse;font-family:'Inter',Arial,Helvetica,sans-serif;">

    <!-- HEADER with slanted background -->
    <tr>
      <td style="padding:0;background:#4169E1;background:linear-gradient(90deg,#4169E1,#8B5CF6)">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td class="mobile-padding" style="padding:20px;text-align:center;position:relative;">
              <div style="text-align:left;padding-bottom:10px;">
                <img src="{header_logo}" width="50" style="display:inline-block;">
              </div>
              <img src="{icon_career}" alt="Career Ladder" class="header-image" width="200"
                style="margin:0 auto;display:block;">
              <h1 class="mobile-heading" style="font-size:24px;font-weight:bold;margin:0 0 5px;color:#fff;">Hi {name}
                👋,</h1>
              <p class="mobile-text" style="font-size:16px;line-height:22px;margin:0;color:#fff;">We are delighted to
                accompany you on every
                step of your coding journey, from conquering your first easy problem to mastering the toughest
                challenge.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:0;line-height:0;font-size:0;height:30px;">
              <div
                style="width:100%;height:30px;background:linear-gradient(to bottom right, transparent 49%, #fafafa 50%);">
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>

    <!-- OUR STORY -->
    <tr>
      <td class="mobile-padding" style="padding:20px;text-align:center;background:#fff;">
        <h3 class="mobile-subheading" style="margin:0;font-size:20px;font-weight:bold;color:#2c0247"><img
            src="{icon_book}" alt="Icon" class="icon-small" width="30"
            style="vertical-align:middle;margin-right:8px;">Our Story</h3>
        <div style="width:80px;height:6px;background:#738CD9;border-radius:15px;margin:8px auto 0;"></div>
        <div class="mobile-full-width"
          style="margin:15px auto 0;background:#f9f9f9;box-shadow:0 2px 4px rgba(0,0,0,0.08);padding:20px;max-width:560px;">
          <p class="mobile-text" style="margin:0;font-size:16px;line-height:22px;color:#353535;">
            Stuck in the DSA maze? We were too..until we built <strong><a href="https://mydsabuddy.com"
                style="color:#4655da;text-decoration:none;">MyDSABuddy</a></strong> as your trusty sidekick. From
            motivational cheers 🎉 to smart insights 🔍, we're here to turn challenges into wins! 🌟
          </p>
        </div>
      </td>
    </tr>

    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>

    <!-- HOW WE HELP -->
    <tr>
      <td class="mobile-padding" style="padding-top:20px;padding-bottom:10px;text-align:center;background:#dcdff7;">
        <h3 class="mobile-subheading" style="margin:0;font-size:18px;font-weight:bold;color:#2c0247;">
          <img src="{icon_help}" alt="Icon" width="30"
            style="vertical-align:middle;margin-right:8px;display:inline-block;">
          How We Help You Succeed
        </h3>
      </td>
    </tr>

    <tr>
      <td class="mobile-padding" style="padding:20px;background:#dcdff7;">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;">

          <!-- ITEM 1 -->
          <tr>
            <td width="100%" style="padding:15px;text-align:center;vertical-align:top;">
              <table align="center" width="80" height="80" cellpadding="0" cellspacing="0"
                style="background:#ffffff;border-radius:50%;margin:0 auto 15px;">
                <tr>
                  <td align="center" valign="middle">
                    <img src="{icon_hand}" alt="AI Analysis" width="50" style="display:block;">
                  </td>
                </tr>
              </table>
              <h4 style="font-size:16px;font-weight:600;color:#2c0247;margin:0 0 8px;">AI Analysis</h4>
              <p style="font-size:14px;line-height:20px;color:#353535;margin:0;">
                Our AI reviews your coding activities to uncover patterns in your problem-solving.
              </p>
            </td>
          </tr>

          <!-- ITEM 2 -->
          <tr>
            <td width="100%" style="padding:15px;text-align:center;vertical-align:top;">
              <table align="center" width="80" height="80" cellpadding="0" cellspacing="0"
                style="background:#ffffff;border-radius:50%;margin:0 auto 15px;">
                <tr>
                  <td align="center" valign="middle">
                    <img src="{icon_curator}" alt="Daily Curation" width="50" style="display:block;">
                  </td>
                </tr>
              </table>
              <h4 style="font-size:16px;font-weight:600;color:#2c0247;margin:0 0 8px;">Daily Curation</h4>
              <p style="font-size:14px;line-height:20px;color:#353535;margin:0;">
                Every day, we curate problems tailored to your goals and revision needs.
              </p>
            </td>
          </tr>

          <!-- ITEM 3 -->
          <tr>
            <td width="100%" style="padding:15px;text-align:center;vertical-align:top;">
              <table align="center" width="80" height="80" cellpadding="0" cellspacing="0"
                style="background:#ffffff;border-radius:50%;margin:0 auto 15px;">
                <tr>
                  <td align="center" valign="middle">
                    <img src="{icon_loop}" alt="Smart Feedback" width="50" style="display:block;">
                  </td>
                </tr>
              </table>
              <h4 style="font-size:16px;font-weight:600;color:#2c0247;margin:0 0 8px;">Smart Feedback</h4>
              <p style="font-size:14px;line-height:20px;color:#353535;margin:0;">
                We retrieve your submissions and deliver detailed feedback highlighting strengths and areas to improve.
              </p>
            </td>
          </tr>

          <!-- ITEM 4 -->
          <tr>
            <td width="100%" style="padding:15px;text-align:center;vertical-align:top;">
              <table align="center" width="80" height="80" cellpadding="0" cellspacing="0"
                style="background:#ffffff;border-radius:50%;margin:0 auto 15px;">
                <tr>
                  <td align="center" valign="middle">
                    <img src="{icon_stairs}" alt="Progress Tracking" width="50" style="display:block;">
                  </td>
                </tr>
              </table>
              <h4 style="font-size:16px;font-weight:600;color:#2c0247;margin:0 0 8px;">Progress Tracking</h4>
              <p style="font-size:14px;line-height:20px;color:#353535;margin:0;">
                Track your growth, streaks, and milestones from your personalized dashboard.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>


    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>
    <!-- DASHBOARD BUTTON -->
    <tr>
      <td class="mobile-padding" style="padding:20px;text-align:center;background:#fff;">
        <a href="{dashboard_url}" class="responsive-button" style="background:#4169E1;background:linear-gradient(90deg,#4169E1,#8B5CF6);
                        padding:14px 36px;
                        color:#fff;
                        text-decoration:none;
                        border-radius:4px;
                        font-size:16px;
                        display:inline-block;
                        text-align:center;
                        width:160px;">
          View Dashboard
        </a>
      </td>
    </tr>

    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>

    <!-- STATS TABLE -->
    <tr>
      <td class="mobile-padding" style="padding:0 20px;background:#fff;">
        <h3 class="mobile-subheading" style="margin:0;font-size:20px;font-weight:bold;text-align:center;color:#2c0247">
          🔍 Your Starting Snapshot
        </h3>
        <table cellspacing="0" cellpadding="0" class="stats-table"
          style="margin:15px auto 0;border-collapse:collapse;width:100%;max-width:600px;font-size:16px;">
          <tr>
            <th class="mobile-text"
              style="padding:10px;background:#4169E1;background:linear-gradient(90deg,#8B5CF6,#4169E1);color:#fff;text-align:left;">
              Category</th>
            <th class="mobile-text"
              style="padding:10px;background:#4169E1;background:linear-gradient(90deg,#4169E1,#8B5CF6);color:#fff;text-align:right;">
              Details</th>
          </tr>
          <tr style="background:#f5f5f5;">
            <td class="mobile-text" style="padding:10px;">Total Solved</td>
            <td class="mobile-text" style="padding:10px;" align="right">{total_solved}</td>
          </tr>
          <tr style="background:#fff;">
            <td class="mobile-text" style="padding:10px;">Success Rate</td>
            <td class="mobile-text" style="padding:10px;" align="right">{success_rate:.2f}%</td>
          </tr>
          <tr style="background:#f5f5f5;">
            <td class="mobile-text" style="padding:10px;">Easy Problems</td>
            <td class="mobile-text" style="padding:10px;" align="right">{easy_count}</td>
          </tr>
          <tr style="background:#fff;">
            <td class="mobile-text" style="padding:10px;">Medium Problems</td>
            <td class="mobile-text" style="padding:10px;" align="right">{medium_count}</td>
          </tr>
          <tr style="background:#f5f5f5;">
            <td class="mobile-text" style="padding:10px;">Hard Problems</td>
            <td class="mobile-text" style="padding:10px;" align="right">{hard_count}</td>
          </tr>
          <tr style="background:#fff;">
            <td class="mobile-text" style="padding:10px;">Avg. Attempts/Question</td>
            <td class="mobile-text" style="padding:10px;" align="right">{average_attempts:.1f}</td>
          </tr>
          <tr style="background:#f5f5f5;">
            <td class="mobile-text" style="padding:10px;">Strong Areas</td>
            <td class="mobile-text" style="padding:10px;" align="right">{strong_areas}</td>
          </tr>
          <tr style="background:#fff;">
            <td class="mobile-text" style="padding:10px;">Areas to Grow</td>
            <td class="mobile-text" style="padding:10px;" align="right">{weak_areas}</td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>

    <!-- TIP -->
    <tr>
      <td class="mobile-padding" style="padding:0 20px;">
        <div class="mobile-text"
          style="font-size:16px;margin-top:0;background:#ffebee;padding:10px;color:#333;text-align:center;border-radius:50px;">
          💡 Tip: Focus on consistency to boost your scores!💪</div>
      </td>
    </tr>

    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>
    <!-- NEXT STEPS -->
    <tr>
      <td class="mobile-padding" style="padding:20px;text-align:center;background:#ffe3e3;">
        <h3 class="mobile-subheading" style="font-size:18px;margin:0 0 20px;font-weight:bold;color:#2c0247">🚀 Next
          Steps</h3>
        <p class="mobile-text" style="font-size:16px;line-height:24px;margin:0 0 24px;">Keep an eye out for our next
          email with your
          personalized question at your chosen time slot. In the meantime, stay focused—each problem you tackle brings
          you one step closer to mastery! 💪 <br><br>If you need any assistance, reach out at <a
            href="mailto:{support_email}">{support_email}</a> or share feedback at <a
            href="mailto:{feedback_email}">{feedback_email}</a>.</p>
    
        <div style="text-align:center;">
          <a href="{dashboard_url}" class="responsive-button" style="background:#4169E1;background:linear-gradient(90deg,#4169E1,#8B5CF6);
            padding:14px 36px;
            color:#fff;
            text-decoration:none;
            border-radius:6px;
            font-size:16px;
            display:inline-block;
            text-align:center;
            max-width:260px;
            width:260px;
            margin:8px auto;">
            Visit Dashboard
          </a>
          <br class="mobile-show" style="display:none;">
          <a href="{whatsapp_url}" class="responsive-button" style="background:#469A42;
            padding:14px 36px;
            color:#fff;
            text-decoration:none;
            border-radius:6px;
            font-size:16px;
            display:inline-block;
            text-align:center;
            max-width:260px;
            width:260px;
            margin:8px auto;">
            Join our Community
            <img src="{icon_wp}" alt="WhatsApp" width="20" height="20" style="vertical-align:middle;margin-left:6px;">
          </a>
        </div>
      </td>
    <tr>
      <td class="spacer-height" style="height:20px;"></td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td
        style="padding:0;background:#4169E1;background:linear-gradient(90deg,#4169E1,#8B5CF6) center bottom/cover no-repeat;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:0;line-height:0;font-size:0;height:30px;">
              <div
                style="width:100%;height:30px;background:linear-gradient(to top left, transparent 49%, #fafafa 50%);">
              </div>
            </td>
          </tr>
          <tr>
            <td class="mobile-padding" style="padding:20px;text-align:center;position:relative;">
              <p class="mobile-text" style="font-size:16px;margin:0 0 5px;color:#fff;">You're off to a great start! Keep
                coding and watch
                your skills soar! <img src="{icon_shine}" alt="shine" class="icon-small" width="14" height="14"
                  style="display:inline-block;"> </p>
              <p class="mobile-text" style="font-size:16px;margin:0 0 5px;color:#fff;">Made with <img src="{icon_love}"
                  alt="heart" class="icon-small" width="14" height="14" style="display:inline-block;"> by Team
                MyPlacementBuddy</p>
              <div style="margin:5px 0;"><img src="{header_logo}" class="dark-logo" alt="MyDSABuddy Logo" width="50"
                  style="display:block;margin:0 auto;"></div>
              <p style="margin:10px 0;">
                <a href="{INSTAGRAM_URL}" style="text-decoration:none;margin:0 8px;display:inline-block;">
                  <img src="{icon_insta}" alt="Instagram" class="social-icon" width="32" height="32"
                    style="display:block;">
                </a>
                <a href="{X_URL}" style="text-decoration:none;margin:0 8px;display:inline-block;">
                  <img src="{icon_x}" alt="X" class="social-icon" width="32" height="32" style="display:block;">
                </a>
                <a href="{LINKEDIN_URL}" style="text-decoration:none;margin:0 8px;display:inline-block;">
                  <img src="{icon_linkedin}" alt="LinkedIn" class="social-icon" width="32" height="32"
                    style="display:block;">
                </a>
              </p>
              <p class="mobile-text" style="font-size:12px;margin:0;color:#f0f0f0;">© 2026 MyPlacementBuddy. All Rights
                Reserved.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>
</body>

</html>
"""
    return html_content

# -----------------------------------------------------------------------------
# Route handlers
# -----------------------------------------------------------------------------
@app.function_name("welcome_email_trigerr")
@app.route(route="welcome-email", auth_level=func.AuthLevel.ANONYMOUS)
def send_welcome_email_route(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("/welcome-email trigger received.")
    if req.method != "POST":
        return func.HttpResponse("Only POST is allowed.", status_code=405)
    try:
        body = req.get_json()
        env = body.get("env")
        logger.info(f"Received request body: {body}")
        username = body.get("username", "")
        if not username:
            logger.warning("Missing or invalid 'username' in request body.")
            return func.HttpResponse("Missing or invalid 'username' in request body.", status_code=400)
        coll = get_mongo_collection("user_fullscorecard", env=env)
        doc = coll.find_one({"userId": username})
        logger.info(f"doc extracted: {doc}")
        if not doc:
            logger.warning(f"User '{username}' not found in database.")
            return func.HttpResponse(f"User '{username}' not found.", status_code=404)
        mail_html = generate_welcome_email(doc)
        subject = "🌟 Launch Your AI-Driven Coding Adventure with MyDSABuddy!"
        smtp_cfg = _get_smtp_config()
        logger.info(f"SMTP config: host={smtp_cfg['host']}, port={smtp_cfg['port']}")
        send_email(smtp_cfg, doc["email"], subject, mail_html)
        logger.info(f"Email processing completed for {doc['email']}")
        return func.HttpResponse(
            json.dumps({"welcome_email_sent": True}),
            status_code=200,
            mimetype="application/json"
        )
    except ValueError as e:
        logger.error(f"Invalid JSON in request: {str(e)}")
        return func.HttpResponse("Invalid JSON.", status_code=400)
    except Exception as exc:
        logger.error(f"Unhandled error in welcome-email: {str(exc)}", exc_info=True)
        return func.HttpResponse("Internal server error.", status_code=500)

        
@app.function_name("daily_ques_email")
@app.route(route="daily-ques-email", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def send_dsa_email_route(req: func.HttpRequest) -> func.HttpResponse:
    if req.method != "POST":
        return func.HttpResponse("Only POST allowed.", status_code=405)

    try:
        user_data = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON.", status_code=400)

    recipient = user_data.get("email")
    if not recipient:
        return func.HttpResponse("Missing 'email' in request body.", status_code=400)

    try:
        html_content = generate_github_style_html(user_data)
    except Exception as e:
        logger.error("Error generating daily-ques HTML: %s", e, exc_info=True)
        return func.HttpResponse("Error generating email content.", status_code=500)

    subject = f"MyDSABuddy - DSA Challenge: {user_data.get('problem_title', 'Today’s Challenge')}"

    try:
        smtp_cfg = _get_smtp_config()
        send_email(smtp_cfg, recipient, subject, html_content)
    except Exception as e:
        logger.error("Error sending daily-ques email: %s", e, exc_info=True)
        return func.HttpResponse("Failed to send email.", status_code=500)

    return func.HttpResponse(
        json.dumps({"daily_ques_sent": True}),
        status_code=200,
        mimetype="application/json"
    )

@app.function_name("daily_eval_email")
@app.route(route="daily-eval-email", auth_level=func.AuthLevel.ANONYMOUS)
def send_feedback_email_route(req: func.HttpRequest) -> func.HttpResponse:
    if req.method != "POST":
        return func.HttpResponse("Only POST allowed.", status_code=405)

    try:
        user_data = req.get_json()
        logger.info(user_data)
    except ValueError:
        return func.HttpResponse("Invalid JSON.", status_code=400)

    feedbacks = user_data.get("feedbacks") or []
    if not feedbacks:
        return func.HttpResponse("Missing 'feedbacks' in request body.", status_code=400)

    recipient = feedbacks[0].get('email')
    if not recipient:
        return func.HttpResponse("Missing 'email' in feedbacks.", status_code=400)

    report_flag = user_data.get("report", True)

    try:
        if report_flag:
            html_content = build_eval_st_template(user_data)
        else:
            html_content = build_no_submission_template(user_data)
    except Exception as e:
        logger.error("Error generating daily-eval HTML: %s", e, exc_info=True)
        return func.HttpResponse("Error generating email content.", status_code=500)

    subject = f"🔍 MyDSABuddy Feedback Summary: {feedbacks[0]['problem_title'].title()}"

    try:
        smtp_cfg = _get_smtp_config()
        send_email(smtp_cfg, recipient, subject, html_content)
    except Exception as e:
        logger.error("Error sending daily-eval email: %s", e, exc_info=True)
        return func.HttpResponse("Failed to send email.", status_code=500)

    return func.HttpResponse(
        json.dumps({"daily_eval_sent": True}),
        status_code=200,
        mimetype="application/json"
    )
# -----------------------------------------------------------------------------
# Redis client (module-level singleton for warm-start reuse)
# -----------------------------------------------------------------------------
import redis as redis_lib

_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(
            host=os.environ["REDIS_HOST"],
            port=int(os.environ.get("REDIS_PORT", 6379)),
            password=os.environ.get("REDIS_PASSWORD", None),
            ssl=os.environ.get("REDIS_USE_SSL", "false").lower() == "true",
            decode_responses=True,
        )
    return _redis_client


# -----------------------------------------------------------------------------
# Filter-based ID resolution helper
# -----------------------------------------------------------------------------
def _resolve_ids_from_filter(
    collection: str,
    filter_dict: dict,
    env: Optional[str] = None,
) -> list[str]:
    """
    Query MongoDB with a projection of {_id: 1} only to cheaply resolve
    which document IDs match the given filter.

    Returns a list of string IDs that can be used to build entity cache keys.
    Only fetches IDs — no document payloads are transferred over the wire.
    """
    try:
        coll = get_mongo_collection(collection, env=env)
        cursor = coll.find(filter_dict, {"_id": 1})
        ids = [str(doc["_id"]) for doc in cursor]
        logger.info(
            "FILTER RESOLUTION: filter=%s matched %d documents in '%s' (env=%s)",
            filter_dict,
            len(ids),
            collection,
            env,
        )
        return ids
    except Exception as exc:
        logger.error(
            "FILTER RESOLUTION failed for collection='%s' filter=%s: %s",
            collection,
            filter_dict,
            exc,
        )
        raise

# -----------------------------------------------------------------------------
# Refresh route
# -----------------------------------------------------------------------------
@app.function_name("cache_refresh")
@app.route(
    route="refresh-cache",
    methods=["POST"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def refresh_cache_route(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("/refresh-cache trigger received.")

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON.", status_code=400)

    user_id    = body.get("user_id", "").strip()
    collection = body.get("collection", "").strip().lower()
    env        = body.get("env", "prod").strip().lower()
    doc_id     = body.get("doc_id", "").strip() or None
    flush_all  = body.get("flush_all", False)
    # Arbitrary MongoDB filter — used to resolve matching document IDs
    # and delete their entity cache keys.
    # Example: {"difficulty": "easy"} or {"tags": "arrays", "difficulty": "medium"}
    filter_dict: Optional[dict] = body.get("filter") or None

    # filter must be a dict if provided
    if filter_dict is not None and not isinstance(filter_dict, dict):
        return func.HttpResponse(
            "'filter' must be a JSON object (e.g. {\"difficulty\": \"easy\"})",
            status_code=400,
        )

    # filter requires collection to know which MongoDB collection to query
    if filter_dict and not collection:
        return func.HttpResponse(
            "'collection' is required when 'filter' is provided.",
            status_code=400,
        )

    # Validation: at least one targeting field required unless flush_all is set
    if not flush_all and not user_id and not collection:
        return func.HttpResponse(
            "Either user_id, collection, or flush_all:true is required.",
            status_code=400
        )

    try:
        r = get_redis_client()
        r.ping()
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)
        return func.HttpResponse(
            f"Redis connection error: {exc}",
            status_code=500
        )

    try:

        # ==========================================================
        # FLUSH ALL CACHE
        # Triggered when flush_all: true is passed.
        # Scans and deletes every cache key written by this service:
        #   e:*          — entity keys
        #   q:*          — versioned query keys
        #   ver:*        — version counter keys
        #   user_keys:*  — user key tracking sets
        # User-scoped keys ({userId}:{collection}) are caught by scanning
        # for keys that contain exactly one colon and are not in the
        # patterns above (they follow the {userId}:{collection} shape).
        # Uses SCAN instead of FLUSHDB so this stays safe if Redis is
        # shared with non-cache data.
        # ==========================================================
        if flush_all:
            CACHE_PATTERNS = ["e:*", "q:*", "ver:*", "user_keys:*"]
            all_deleted: list[str] = []

            for pattern in CACHE_PATTERNS:
                for key in r.scan_iter(match=pattern):
                    r.delete(key)
                    all_deleted.append(key)

            logger.info(
                "FLUSH ALL: deleted %d cache keys across patterns %s",
                len(all_deleted),
                CACHE_PATTERNS,
            )

            return func.HttpResponse(
                json.dumps({
                    "cache_refresh": True,
                    "invalidation_strategy": "flush_all",
                    "deleted_count": len(all_deleted),
                    "deleted_keys": all_deleted,
                }),
                status_code=200,
                mimetype="application/json",
            )

        # ==========================================================
        # USER-SCOPED INVALIDATION
        # Triggered when user_id is present.
        # Wipes every cache key that belongs to this user across ALL
        # collections (e.g. user_fullscorecard, user_profile, user_stats)
        # so no collection is left holding stale data after a user update.
        # ==========================================================
        if user_id:

            # ----------------------------------------------------------
            # Always wipe ALL user-scoped keys for this user across every
            # collection (user_id:* pattern).  A user's data can live in
            # multiple collections.  Invalidating only one collection would
            # leave stale data in the others.
            # ----------------------------------------------------------
            user_key_set_name = f"user_keys:{user_id}"
            tracked_keys = r.smembers(user_key_set_name)

            if tracked_keys:
                # Preferred path: delete only the keys we know about,
                # then drop the tracking set itself.
                keys_to_delete = list(tracked_keys) + [user_key_set_name]
                deleted_count = r.delete(*keys_to_delete)
                deleted_keys = list(tracked_keys)
                logger.info(
                    "USER-SCOPED INVALIDATION (set-tracked): deleted %d keys for user %s: %s",
                    deleted_count,
                    user_id,
                    deleted_keys,
                )
            else:
                # Fallback: no tracking set present — use scan_iter so we
                # don't miss any existing keys for this user.
                deleted_keys = []
                for key in r.scan_iter(match=f"{user_id}:*"):
                    r.delete(key)
                    deleted_keys.append(key)
                logger.info(
                    "USER-SCOPED INVALIDATION (scan fallback): deleted %d keys for user %s",
                    len(deleted_keys),
                    user_id,
                )

            result = {
                "invalidation_strategy": "user_scoped",
                "user_id": user_id,
                "deleted_keys": deleted_keys,
                "deleted_count": len(deleted_keys),
            }

            # ----------------------------------------------------------
            # DUAL INVALIDATION — SHARED COLLECTION CACHE
            # If a specific collection was supplied, also bump its version
            # counter and optionally remove the entity-level key.  This
            # covers shared (non-user-scoped) caches that may hold the
            # same document.
            # ----------------------------------------------------------
            if collection:
                # -- Single doc invalidation --
                if doc_id:
                    entity_key = f"e:{collection}:{env}:{doc_id}"
                    r.delete(entity_key)
                    logger.info("Dual invalidation — shared collection entity DEL: %s", entity_key)
                    result["also_deleted_entity_key"] = entity_key

                # -- Filter-based entity invalidation --
                if filter_dict:
                    matched_ids = _resolve_ids_from_filter(collection, filter_dict, env=env)
                    if matched_ids:
                        entity_keys = [f"e:{collection}:{env}:{did}" for did in matched_ids]
                        deleted_count = r.delete(*entity_keys)
                        logger.info(
                            "Dual invalidation — filter entity DEL: %d keys deleted for filter=%s",
                            deleted_count,
                            filter_dict,
                        )
                        result["also_filter_matched_ids"] = matched_ids
                        result["also_filter_deleted_entity_count"] = deleted_count
                    else:
                        logger.info("Dual invalidation — filter matched 0 documents, no entity keys deleted.")
                        result["also_filter_matched_ids"] = []
                        result["also_filter_deleted_entity_count"] = 0

                version_key = f"ver:{collection}:{env}"
                new_version = r.incr(version_key)
                logger.info(
                    "Dual invalidation — shared collection version INCR: %s -> %d",
                    version_key,
                    new_version,
                )
                result["also_invalidated_shared_collection"] = True
                result["collection"] = collection
                result["new_version"] = new_version
            else:
                result["note"] = (
                    "Shared collection cache not invalidated — pass 'collection' in the "
                    "request body to also bump the shared-collection version"
                )

        # ==========================================================
        # SHARED COLLECTION INVALIDATION
        # Triggered when only collection is present (no user_id).
        # Bumps the version counter for the entire collection so every
        # cached query result against it is treated as stale.
        # Optionally removes a single document's entity-level key too.
        # ==========================================================
        else:

            result = {
                "invalidation_strategy": "shared_collection",
                "collection": collection,
                "env": env
            }

            # -- Single doc invalidation --
            if doc_id:
                entity_key = f"e:{collection}:{env}:{doc_id}"
                deleted = r.delete(entity_key)
                logger.info(
                    "SHARED COLLECTION INVALIDATION — entity DEL %s -> %s",
                    entity_key,
                    deleted,
                )
                result["entity_key_deleted"] = entity_key
                result["entity_key_existed"] = bool(deleted)

            # -- Filter-based entity invalidation --
            if filter_dict:
                matched_ids = _resolve_ids_from_filter(collection, filter_dict, env=env)
                if matched_ids:
                    entity_keys = [f"e:{collection}:{env}:{did}" for did in matched_ids]
                    deleted_count = r.delete(*entity_keys)
                    logger.info(
                        "FILTER INVALIDATION — deleted %d entity keys for filter=%s in '%s' (env=%s)",
                        deleted_count,
                        filter_dict,
                        collection,
                        env,
                    )
                    result["filter"] = filter_dict
                    result["filter_matched_ids"] = matched_ids
                    result["filter_deleted_entity_count"] = deleted_count
                else:
                    logger.info(
                        "FILTER INVALIDATION — filter=%s matched 0 documents in '%s', no entity keys deleted.",
                        filter_dict,
                        collection,
                    )
                    result["filter"] = filter_dict
                    result["filter_matched_ids"] = []
                    result["filter_deleted_entity_count"] = 0

            # Increment version to invalidate all cached query keys for this collection.
            # This orphans every q:v{old}:... key regardless of whether it was a
            # filter-based, doc_id, or collection-wide invalidation.
            version_key = f"ver:{collection}:{env}"
            new_version = r.incr(version_key)
            logger.info(
                "SHARED COLLECTION INVALIDATION — version INCR %s -> %d",
                version_key,
                new_version,
            )
            result["version_key"] = version_key
            result["new_version"] = new_version

        return func.HttpResponse(
            json.dumps({
                "cache_refresh": True,
                **result
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as exc:
        logger.error(
            "Error during cache refresh: %s",
            exc,
            exc_info=True
        )

        return func.HttpResponse(
            "Internal server error.",
            status_code=500
        )