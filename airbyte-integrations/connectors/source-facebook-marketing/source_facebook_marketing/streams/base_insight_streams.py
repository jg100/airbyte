#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#

import logging
from typing import Any, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Union

import airbyte_cdk.sources.utils.casing as casing
import pendulum
from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.streams.core import package_name_from_class
from airbyte_cdk.sources.utils.schema_helpers import ResourceSchemaLoader
from cached_property import cached_property
from source_facebook_marketing.streams.async_job import AsyncJob, InsightAsyncJob
from source_facebook_marketing.streams.async_job_manager import InsightAsyncJobManager

from .base_streams import FBMarketingIncrementalStream

logger = logging.getLogger("airbyte")


class AdsInsights(FBMarketingIncrementalStream):
    """doc: https://developers.facebook.com/docs/marketing-api/insights"""

    cursor_field = "date_start"
    use_batch = False
    enable_deleted = False

    ALL_ACTION_ATTRIBUTION_WINDOWS = [
        "1d_click",
        "7d_click",
        "28d_click",
        "1d_view",
        "7d_view",
        "28d_view",
    ]

    ALL_ACTION_BREAKDOWNS = [
        "action_type",
        "action_target_id",
        "action_destination",
    ]

    # Facebook store metrics maximum of 37 months old. Any time range that
    # older that 37 months from current date would result in 400 Bad request
    # HTTP response.
    # https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/#overview
    INSIGHTS_RETENTION_PERIOD = pendulum.duration(months=37)
    # Facebook freezes insight data 28 days after it was generated, which means that all data
    # from the past 28 days may have changed since we last emitted it, so we retrieve it again.
    INSIGHTS_LOOKBACK_PERIOD = pendulum.duration(days=28)

    action_breakdowns = ALL_ACTION_BREAKDOWNS
    level = "ad"
    action_attribution_windows = ALL_ACTION_ATTRIBUTION_WINDOWS
    time_increment = 1

    breakdowns = []

    def __init__(
        self,
        name: str = None,
        fields: List[str] = None,
        breakdowns: List[str] = None,
        action_breakdowns: List[str] = None,
        time_increment: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._start_date = self._start_date.date()
        self._end_date = self._end_date.date()
        self._fields = fields
        self.action_breakdowns = action_breakdowns or self.action_breakdowns
        self.breakdowns = breakdowns or self.breakdowns
        self.time_increment = time_increment or self.time_increment
        self._new_class_name = name

        # state
        self._cursor_value: Optional[pendulum.Date] = None  # latest period that was read
        self._next_cursor_value = self._get_start_date()
        self._completed_slices = set()

    @property
    def name(self) -> str:
        """We override stream name to let the user change it via configuration."""
        name = self._new_class_name or self.__class__.__name__
        return casing.camel_to_snake(name)

    @property
    def primary_key(self) -> Optional[Union[str, List[str], List[List[str]]]]:
        """Build complex PK based on slices and breakdowns"""
        return ["date_start", "account_id", "ad_id"] + self.breakdowns

    def list_objects(self, params: Mapping[str, Any]) -> Iterable:
        """Because insights has very different read_records we don't need this method anymore"""

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        """Waits for current job to finish (slice) and yield its result"""

        today = pendulum.today(tz="UTC").date()
        date_start = stream_state and stream_state.get("date_start")
        if date_start:
            date_start = pendulum.parse(date_start).date()

        job = stream_slice["insight_job"]
        for obj in job.get_result():
            record = obj.export_all_data()
            if date_start:
                updated_time = pendulum.parse(record["updated_time"]).date()
                if updated_time <= date_start or updated_time >= today:
                    continue
            yield record

        self._completed_slices.add(job.interval.start)
        if job.interval.start == self._next_cursor_value:
            self._advance_cursor()

    @property
    def state(self) -> MutableMapping[str, Any]:
        """State getter, the result can be stored by the source"""
        if self._cursor_value:
            return {
                self.cursor_field: self._cursor_value.isoformat(),
                "slices": [d.isoformat() for d in self._completed_slices],
                "time_increment": self.time_increment,
            }

        if self._completed_slices:
            return {
                "slices": [d.isoformat() for d in self._completed_slices],
                "time_increment": self.time_increment,
            }

        return {}

    @state.setter
    def state(self, value: Mapping[str, Any]):
        """State setter, will ignore saved state if time_increment is different from previous."""
        # if the time increment configured for this stream is different from the one in the previous state
        # then the previous state object is invalid and we should start replicating data from scratch
        # to achieve this, we skip setting the state
        if value.get("time_increment", 1) != self.time_increment:
            logger.info(f"Ignoring bookmark for {self.name} because of different `time_increment` option.")
            return

        self._cursor_value = pendulum.parse(value[self.cursor_field]).date() if value.get(self.cursor_field) else None
        self._completed_slices = set(pendulum.parse(v).date() for v in value.get("slices", []))
        self._next_cursor_value = self._get_start_date()

    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]):
        """Update stream state from latest record

        :param current_stream_state: latest state returned
        :param latest_record: latest record that we read
        """
        return self.state

    def _date_intervals(self) -> Iterator[pendulum.Date]:
        """Get date period to sync"""
        yesterday = pendulum.yesterday(tz="UTC").date()
        end_date = min(self._end_date, yesterday)
        if end_date < self._next_cursor_value:
            return
        date_range = end_date - self._next_cursor_value
        yield from date_range.range("days", self.time_increment)

    def _advance_cursor(self):
        """Iterate over state, find continuing sequence of slices. Get last value, advance cursor there and remove slices from state"""
        for ts_start in self._date_intervals():
            if ts_start not in self._completed_slices:
                self._next_cursor_value = ts_start
                break
            self._completed_slices.remove(ts_start)
            self._cursor_value = ts_start

    def _generate_async_jobs(self, params: Mapping) -> Iterator[AsyncJob]:
        """Generator of async jobs

        :param params:
        :return:
        """

        today = pendulum.today(tz="UTC").date()
        refresh_date = today - self.INSIGHTS_LOOKBACK_PERIOD

        for ts_start in self._date_intervals():
            if ts_start in self._completed_slices:
                if ts_start < refresh_date:
                    continue
                self._completed_slices.remove(ts_start)
            ts_end = ts_start + pendulum.duration(days=self.time_increment - 1)
            interval = pendulum.Period(ts_start, ts_end)
            yield InsightAsyncJob(api=self._api.api, edge_object=self._api.account, interval=interval, params=params)

    def stream_slices(
        self, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:

        """Slice by date periods and schedule async job for each period, run at most MAX_ASYNC_JOBS jobs at the same time.
        This solution for Async was chosen because:
        1. we should commit state after each successful job
        2. we should run as many job as possible before checking for result
        3. we shouldn't proceed to consumption of the next job before previous succeed

        generate slice only if it is not in state,
        when we finished reading slice (in read_records) we check if current slice is the next one and do advance cursor

        when slice is not next one we just update state with it
        to do so source will check state attribute and call get_state,
        """
        if stream_state:
            self.state = stream_state

        manager = InsightAsyncJobManager(api=self._api, jobs=self._generate_async_jobs(params=self.request_params()))
        for job in manager.completed_jobs():
            yield {"insight_job": job}

    def _get_start_date(self) -> pendulum.Date:
        """Get start date to begin sync with. It is not that trivial as it might seem.
        There are few rules:
            - don't read data older than start_date
            - re-read data within last 28 days
            - don't read data older than retention date
        Also there are difference between start_date and cursor_value in how the value must be interpreted:
            - cursor - last value that we synced
            - start_date - the first value that should be synced

        :return: the first date to sync
        """
        today = pendulum.today(tz="UTC").date()
        oldest_date = today - self.INSIGHTS_RETENTION_PERIOD
        refresh_date = today - self.INSIGHTS_LOOKBACK_PERIOD

        if self._cursor_value:
            start_date = self._cursor_value + pendulum.duration(days=self.time_increment)
            if start_date > refresh_date:
                logger.info(
                    f"The cursor value within refresh period ({self.INSIGHTS_LOOKBACK_PERIOD}), start sync from {refresh_date} instead."
                )
            start_date = min(start_date, refresh_date)

            if start_date < self._start_date:
                logger.warning(f"Ignore provided state and start sync from start_date ({self._start_date}).")
            start_date = max(start_date, self._start_date)
        else:
            start_date = self._start_date
        if start_date < oldest_date:
            logger.warning(f"Loading insights older then {self.INSIGHTS_RETENTION_PERIOD} is not possible. Start sync from {oldest_date}.")

        return max(oldest_date, start_date)

    def request_params(self, **kwargs) -> MutableMapping[str, Any]:
        return {
            "level": self.level,
            "action_breakdowns": self.action_breakdowns,
            "breakdowns": self.breakdowns,
            "fields": self.fields,
            "time_increment": self.time_increment,
            "action_attribution_windows": self.action_attribution_windows,
        }

    def _state_filter(self, stream_state: Mapping[str, Any]) -> Mapping[str, Any]:
        """Works differently for insights, so remove it"""
        return {}

    def get_json_schema(self) -> Mapping[str, Any]:
        """Add fields from breakdowns to the stream schema
        :return: A dict of the JSON schema representing this stream.
        """
        loader = ResourceSchemaLoader(package_name_from_class(self.__class__))
        schema = loader.get_schema("ads_insights")
        if self._fields:
            schema["properties"] = {k: v for k, v in schema["properties"].items() if k in self._fields}
        if self.breakdowns:
            breakdowns_properties = loader.get_schema("ads_insights_breakdowns")["properties"]
            schema["properties"].update({prop: breakdowns_properties[prop] for prop in self.breakdowns})
        return schema

    @cached_property
    def fields(self) -> List[str]:
        """List of fields that we want to query, for now just all properties from stream's schema"""
        if self._fields:
            return self._fields
        schema = ResourceSchemaLoader(package_name_from_class(self.__class__)).get_schema("ads_insights")
        return list(schema.get("properties", {}).keys())
