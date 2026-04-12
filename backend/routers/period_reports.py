"""
Period Reports Router

Handles Monthly and Quarterly report pages
"""

import os
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.github_service import get_gh_cli_token
from backend.services.period_report_service import PeriodReportService

router = APIRouter(tags=["period-reports"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))


@router.get("/monthly-report/", response_class=HTMLResponse)
def monthly_report_page(request: Request, db: Session = Depends(get_db)):
    """Display monthly report page (last 30 days) - reads from database"""

    # Check configuration
    github_configured = get_gh_cli_token() is not None or os.getenv("GITHUB_TOKEN") is not None
    jira_configured = all(
        [os.getenv("JIRA_SERVER"), os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")]
    )

    # Generate report from database
    report = None
    if github_configured or jira_configured:
        report_service = PeriodReportService(db=db)
        report = report_service.generate_monthly_report()

    return templates.TemplateResponse(
        request,
        "period_reports/monthly.html",
        {
            "report": report,
            "github_configured": github_configured,
            "jira_configured": jira_configured,
            "today": date.today().strftime("%Y-%m-%d"),
        },
    )


@router.get("/quarterly-report/", response_class=HTMLResponse)
def quarterly_report_page(request: Request, db: Session = Depends(get_db)):
    """Display quarterly report page (last 90 days) - reads from database"""

    # Check configuration
    github_configured = get_gh_cli_token() is not None or os.getenv("GITHUB_TOKEN") is not None
    jira_configured = all(
        [os.getenv("JIRA_SERVER"), os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN")]
    )

    # Generate report from database
    report = None
    if github_configured or jira_configured:
        report_service = PeriodReportService(db=db)
        report = report_service.generate_quarterly_report()

    return templates.TemplateResponse(
        request,
        "period_reports/quarterly.html",
        {
            "report": report,
            "github_configured": github_configured,
            "jira_configured": jira_configured,
            "today": date.today().strftime("%Y-%m-%d"),
        },
    )
