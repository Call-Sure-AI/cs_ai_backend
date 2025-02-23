from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.google_sheets.google_sheet_service import (
    list_sheets, get_all_sheet_names, create_new_sheet, update_sheet
)

router = APIRouter()

class SpreadsheetID(BaseModel):
    spreadsheet_id: str

class CreateSheetRequest(BaseModel):
    title: str = "New Spreadsheet"
    data: list

class UpdateSheetRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str
    data: list

@router.post("/list_sheets")
async def api_list_sheets():
    """API Endpoint to fetch all Google Sheets."""
    sheets = list_sheets()
    return sheets


@router.post("/get_sheet_names")
async def api_get_sheet_names(payload: SpreadsheetID):
    """API Endpoint to retrieve all sheet names from a given Google Sheet."""
    if not payload.spreadsheet_id:
        raise HTTPException(status_code=400, detail="spreadsheet_id is required")

    sheet_names = get_all_sheet_names(payload.spreadsheet_id)
    return {"sheets": sheet_names}


@router.post("/create_sheet")
async def api_create_new_sheet(payload: CreateSheetRequest):
    """API Endpoint to create a new Google Sheet."""
    result = create_new_sheet(payload.title, payload.data)
    return result


@router.post("/append_data")
async def api_append_data(payload: UpdateSheetRequest):
    """API Endpoint to append data to an existing sheet."""
    if not payload.spreadsheet_id or not payload.sheet_name:
        raise HTTPException(status_code=400, detail="spreadsheet_id and sheet_name are required")

    result = update_sheet(payload.spreadsheet_id, payload.sheet_name, payload.data, replace=False)
    return result


@router.post("/replace_data")
async def api_replace_data(payload: UpdateSheetRequest):
    """API Endpoint to replace all data in an existing sheet."""
    if not payload.spreadsheet_id or not payload.sheet_name:
        raise HTTPException(status_code=400, detail="spreadsheet_id and sheet_name are required")

    result = update_sheet(payload.spreadsheet_id, payload.sheet_name, payload.data, replace=True)
    return result
