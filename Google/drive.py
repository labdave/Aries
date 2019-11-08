import requests
import logging
from ..web import WebAPI
logger = logging.getLogger(__name__)


class GoogleDriveFile:
    def __init__(self, access_token, file_id):
        self.file_id = file_id
        self._metadata = None
        self.api = WebAPI("https://www.googleapis.com/")
        self.api.add_header(Authorization="Bearer %s" % access_token)

    @property
    def metadata(self):
        if not self._metadata:
            url = "https://www.googleapis.com/drive/v3/files/%s" % self.file_id
            self._metadata = self.api.get_json(url)
        return self._metadata

    @property
    def revisions(self):
        return self.api.get_json("https://www.googleapis.com/drive/v3/files/%s/revisions" % self.file_id)


class GoogleSheet(GoogleDriveFile):
    def get(self, **kwargs):
        """Returns properties of the spreadsheet along with properties and merges of sheets in the spreadsheet.
        By default, data within grids will not be returned. You can include grid data one of two ways:
            1. Specify a field mask listing your desired fields using the fields parameter.
            2. Use key word argument "includeGridData=True".
        If a field mask is set, the includeGridData parameter is ignored
        For large spreadsheets, it is recommended to retrieve only the specific fields of the spreadsheet that you want.

        To retrieve only subsets of the spreadsheet, use the ranges parameter. Multiple ranges can be specified.
        Limiting the range will return only the portions of the spreadsheet that intersect the requested ranges.
        Ranges are specified using A1 notation.

        Args:
            **kwargs: ranges, includeGridData, fields

        Returns: A dictionary containing the information of the spreadsheet.

        See Also:
            https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/get
            https://developers.google.com/sheets/api/guides/concepts#partial_responses
        """
        api_url = "https://sheets.googleapis.com/v4/spreadsheets/%s" % self.file_id
        return self.api.get_json(api_url, **kwargs)

    def values(self, data_range, **kwargs):
        """Gets the values of a specific range.

        Args:
            data_range: A1 notation of a range in a sheet.
                e.g. "SheetName!A1:B5"

        Returns: A dictionary containing the following keys:
            majorDimension:
            range: The actual range in the sheet containing data.
            values: Two 2-D list containing the values.
        """
        return self.api.get_json(
            "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s" % (self.file_id, data_range),
            **kwargs
        )

    def get_data_grid(self, sheet_index=0, value_type="formattedValue"):
        sheets = self.get(includeGridData=True).get("sheets")
        if not sheets:
            return None

        data = sheets[sheet_index].get("data")
        if not data:
            return None

        rows = data[0].get("rowData", [])
        grid = []
        for row in rows:
            values = row.get("values", [])
            row_values = [v.get(value_type) for v in values]
            grid.append(row_values)
        return grid

