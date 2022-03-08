from datetime import datetime, timedelta
from math import ceil
from numbers import Number
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple

import requests
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth.token import TokenAuthenticator


class SourceMagento(AbstractSource):
    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, Optional[Any]]:
        bearer = config['magento_bearer']

        if len(bearer) == 0:
            return False, "Api token is not valid. Check if you have the correct Magento Bearer"
        else:
            return True, None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        start_date = datetime.strptime(config['start_date'], '%Y-%m-%d %H:%M:%S') 
        bearer = config['magento_bearer']
        auth = TokenAuthenticator(bearer)
        return [SalesOrders(
            authenticator=auth,
            start_date=start_date,
            page_size=config['page_size']
        )]


class SalesOrders(HttpStream):
    url_base = "https://skiwebshop.nl/rest/V1/"

    cursor_field = 'updated_at'
    primary_key = 'updated_at'


    def __init__(self, start_date: str, page_size: str, **kwargs):
        super().__init__(**kwargs)
        self.start_date = start_date
        self.page_size = page_size
        self._cursor_value = None

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        res = response.json()
        page = res['search_criteria']['current_page']
        
        total_count = res['total_count']
        page_size = res['search_criteria']['page_size']
        
        if (page * page_size) > total_count:
            return None

        return page + 1

    def request_params(self,
                       stream_state: Mapping[str, Any],
                       stream_slice: Mapping[str, Any] = None,
                       next_page_token: Mapping[str, Any] = None
                       ) -> MutableMapping[str, Any]:
        
        if next_page_token == None:
            page = 1
        else:
            page = next_page_token

        return {
            'searchCriteria[filter_groups][0][filters][0][field]': 'updated_at',
            'searchCriteria[filter_groups][0][filters][0][value]': self.start_date,
            'searchCriteria[filter_groups][0][filters][0][condition_type]': 'gteq',
            'searchCriteria[pageSize]': self.page_size,
            'searchCriteria[currentPage]': page,
            'fields': 'items[increment_id,base_grand_total,customer_firstname,billing_address[country_id],updated_at],search_criteria,total_count'
        }

    def path(self, **kwargs) -> str:
        return "orders"

    def parse_response(self, response: requests.Response, *, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None) -> List:
        res = response.json()
        return res['items']

    @property
    def state(self) -> Mapping[str, Any]:
        if self._cursor_value:
            return {self.cursor_field: self._cursor_value.strftime('%Y-%m-%d %H:%M:%S')}
        else:
            return {self.cursor_field: self.start_date.strftime('%Y-%m-%d %H:%M:%S')}
    
    @state.setter
    def state(self, value: Mapping[str, Any]):
       self._cursor_value = datetime.strptime(value[self.cursor_field], '%Y-%m-%d %H:%M:%S')
    
    def read_records(self, *args, **kwargs) -> Iterable[Mapping[str, Any]]:
        for record in super().read_records(*args, **kwargs):
            if self._cursor_value:
                latest_record_date = datetime.strptime(record[self.cursor_field], '%Y-%m-%d %H:%M:%S')
                print(latest_record_date, self._cursor_value)
                self._cursor_value = max(self._cursor_value, latest_record_date)
            yield record
        
    def _chunk_date_range(self, start_date: datetime) -> List[Mapping[str, Any]]:
        """
        Returns a list of each day between the start date and now.
        The return value is a list of dicts {'date': date_string}.
        """
        dates = []
        while start_date < datetime.now():
            dates.append({self.cursor_field: start_date.strftime('%Y-%m-%d %H:%M:%S')})
            start_date += timedelta(days=1)
        return dates

    def stream_slices(self, sync_mode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None) -> Iterable[Optional[Mapping[str, Any]]]:
        start_date = datetime.strptime(stream_state[self.cursor_field], '%Y-%m-%d %H:%M:%S') if stream_state and self.cursor_field in stream_state else self.start_date
        return self._chunk_date_range(start_date)