from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.http import QueryDict
from elasticsearch_dsl import Q, Search
from elasticsearch_dsl.query import Query
from elasticsearch_dsl.response import Hit, Response
from redis import Redis

from cl.alerts.models import (
    SCHEDULED_ALERT_HIT_STATUS,
    Alert,
    DocketAlert,
    ScheduledAlertHit,
)
from cl.lib.command_utils import logger
from cl.lib.elasticsearch_utils import (
    add_es_highlighting,
    add_fields_boosting,
    build_fulltext_query,
    build_has_child_filters,
    build_highlights_dict,
    build_join_es_filters,
)
from cl.lib.types import CleanData
from cl.search.constants import (
    ALERTS_HL_TAG,
    SEARCH_RECAP_CHILD_HL_FIELDS,
    SEARCH_RECAP_CHILD_QUERY_FIELDS,
)
from cl.search.documents import (
    AudioPercolator,
    ESRECAPDocumentPlain,
    RECAPPercolator,
)
from cl.search.models import SEARCH_TYPES, Docket, RECAPDocument


@dataclass
class DocketAlertReportObject:
    da_alert: DocketAlert
    docket: Docket


class OldAlertReport:
    def __init__(self):
        self.old_alerts = []
        self.very_old_alerts = []
        self.disabled_alerts = []

    @property
    def old_dockets(self):
        return [obj.docket for obj in self.old_alerts]

    @property
    def very_old_dockets(self):
        return [obj.docket for obj in self.very_old_alerts]

    @property
    def disabled_dockets(self):
        return [obj.docket for obj in self.disabled_alerts]

    def total_count(self):
        return (
            len(self.old_alerts)
            + len(self.very_old_alerts)
            + len(self.disabled_alerts)
        )


class InvalidDateError(Exception):
    pass


def percolate_document(
    document_id: str,
    document_index: str,
    search_after: int = 0,
) -> Response:
    """Percolate a document against a defined Elasticsearch Percolator query.

    :param document_id: The document ID in ES index to be percolated.
    :param document_index: The ES document index where the document lives.
    :param search_after: The ES search_after param for deep pagination.
    :return: The response from the Elasticsearch query.
    """

    s = Search(index=AudioPercolator._index._name)
    percolate_query = Q(
        "percolate",
        field="percolator_query",
        index=document_index,
        id=document_id,
    )
    exclude_rate_off = Q("term", rate=Alert.OFF)
    final_query = Q(
        "bool",
        must=[percolate_query],
        must_not=[exclude_rate_off],
    )
    s = s.query(final_query)
    s = add_es_highlighting(
        s, {"type": SEARCH_TYPES.ORAL_ARGUMENT}, alerts=True
    )
    s = s.source(excludes=["percolator_query"])
    s = s.sort("date_created")
    s = s[: settings.ELASTICSEARCH_PAGINATION_BATCH_SIZE]
    if search_after:
        s = s.extra(search_after=search_after)
    return s.execute()


def override_alert_query(
    alert: Alert, cut_off_date: date | None = None
) -> QueryDict:
    """Override the query parameters for a given alert based on its type and an
     optional cut-off date.

    :param alert: The Alert object for which the query will be overridden.
    :param cut_off_date: An optional date used to set a threshold in the query.
    :return: A QueryDict object containing the modified query parameters.
    """

    qd = QueryDict(alert.query.encode(), mutable=True)
    if alert.alert_type == SEARCH_TYPES.ORAL_ARGUMENT:
        qd["order_by"] = "dateArgued desc"
        if cut_off_date:
            qd["argued_after"] = cut_off_date.strftime("%m/%d/%Y")
    else:
        qd["order_by"] = "dateFiled desc"
        if cut_off_date:
            qd["filed_after"] = cut_off_date.strftime("%m/%d/%Y")

    return qd


def alert_hits_limit_reached(alert_pk: int, user_pk: int) -> bool:
    """Check if the alert hits limit has been reached for a specific alert-user
     combination.

    :param alert_pk: The alert_id.
    :param user_pk: The user_id.
    :return: True if the limit has been reached, otherwise False.
    """

    stored_hits = ScheduledAlertHit.objects.filter(
        alert_id=alert_pk,
        user_id=user_pk,
        hit_status=SCHEDULED_ALERT_HIT_STATUS.SCHEDULED,
    )
    hits_count = stored_hits.count()
    if hits_count >= settings.SCHEDULED_ALERT_HITS_LIMIT:
        logger.info(
            f"Skipping hit for Alert ID: {alert_pk}, there are {hits_count} hits stored for this alert."
        )
        return True
    return False


def recap_document_hl_matched(rd_hit: Hit) -> bool:
    """Determine whether HL matched a RECAPDocument text field.

    :param rd_hit: The ES hit.
    :return: True if the hit matched a RECAPDocument field. Otherwise, False.
    """

    matched_rd_hl: set[str] = set()
    rd_hl_fields = set(SEARCH_RECAP_CHILD_HL_FIELDS.keys())
    if hasattr(rd_hit, "highlight"):
        highlights = rd_hit.highlight.to_dict()
        matched_rd_hl.update(
            hl_key
            for hl_key, hl_value in highlights.items()
            for hl in hl_value
            if f"<{ALERTS_HL_TAG}>" in hl
        )
    if matched_rd_hl and matched_rd_hl.issubset(rd_hl_fields):
        return True
    return False


def make_alert_set_key(alert_id: int, document_type: str) -> str:
    """Generate a Redis key for storing alert hits.

    :param alert_id: The ID of the alert.
    :param document_type: The type of document associated with the alert.
    :return: A Redis key string in the format "alert_hits:{alert_id}.{document_type}".
    """
    return f"alert_hits:{alert_id}.{document_type}"


def add_document_hit_to_alert_set(
    r: Redis, alert_id: int, document_type: str, document_id: int
) -> None:
    """Add a document ID to the Redis SET associated with an alert ID.

    :param r: Redis client instance.
    :param alert_id: The alert identifier.
    :param document_type: The type of document associated with the alert.
    :param document_id: The docket identifier to add.
    :return: None
    """
    alert_key = make_alert_set_key(alert_id, document_type)
    r.sadd(alert_key, document_id)


def has_document_alert_hit_been_triggered(
    r: Redis, alert_id: int, document_type: str, document_id: int
) -> bool:
    """Check if a document ID is a member of the Redis SET associated with an
     alert ID.

    :param r: Redis client instance.
    :param alert_id: The alert identifier.
    :param document_type: The type of document associated with the alert.
    :param document_id: The docket identifier to check.
    :return: True if the docket ID is a member of the set, False otherwise.
    """
    alert_key = make_alert_set_key(alert_id, document_type)
    return r.sismember(alert_key, document_id)


def build_plain_percolator_query(cd: CleanData) -> Query:
    """Build a plain query based on the provided clean data for its use in the
    Percolator

    :param cd: The query CleanedData.
    :return: An ES Query object representing the built query.
    """

    plain_query = []
    match cd["type"]:
        case (
            SEARCH_TYPES.RECAP
            | SEARCH_TYPES.DOCKETS
            | SEARCH_TYPES.RECAP_DOCUMENT
        ):
            text_fields = SEARCH_RECAP_CHILD_QUERY_FIELDS.copy()
            text_fields.extend(
                add_fields_boosting(
                    cd,
                    [
                        "description",
                        # Docket Fields
                        "docketNumber",
                        "caseName",
                    ],
                )
            )
            child_filters = build_has_child_filters(cd)
            parent_filters = build_join_es_filters(cd)
            parent_filters.extend(child_filters)

            string_query = build_fulltext_query(
                text_fields, cd.get("q", ""), only_queries=True
            )

            match parent_filters, string_query:
                case [], []:
                    pass
                case [], _:
                    plain_query = Q(
                        "bool",
                        should=string_query,
                        minimum_should_match=1,
                    )
                case _, []:
                    plain_query = Q(
                        "bool",
                        filter=parent_filters,
                    )
                case _, _:
                    plain_query = Q(
                        "bool",
                        filter=parent_filters,
                        should=string_query,
                        minimum_should_match=1,
                    )

    return plain_query


def percolate_docket_or_recap_document(
    document_id: str,
    document_index: str | None = None,
    search_after: int = 0,
) -> Response:
    """Percolate a document against a defined Elasticsearch Percolator query.

    :param document_id: The document ID in ES index to be percolated.
    :param document_index: The ES document index where the document lives.
    :param search_after: The ES search_after param for deep pagination.
    :return: The response from the Elasticsearch query.
    """

    s = Search(index=RECAPPercolator._index._name)
    if document_index:
        percolate_query = Q(
            "percolate",
            field="percolator_query",
            index=document_index,
            id=document_id,
        )
    else:
        rd = RECAPDocument.objects.get(pk=document_id)
        es_document = ESRECAPDocumentPlain().prepare(rd)
        # Remove docket_child to avoid document parsing errors.
        del es_document["docket_child"]
        percolate_query = Q(
            "percolate", field="percolator_query", document=es_document
        )

    exclude_rate_off = Q("term", rate=Alert.OFF)
    final_query = Q(
        "bool",
        must=[percolate_query],
        must_not=[exclude_rate_off],
    )
    s = s.query(final_query)

    if document_index:
        s = add_es_highlighting(s, {"type": SEARCH_TYPES.RECAP}, alerts=True)
    else:
        highlight_options, fields_to_exclude = build_highlights_dict(
            SEARCH_RECAP_CHILD_HL_FIELDS, ALERTS_HL_TAG
        )
        extra_options = {"highlight": highlight_options}
        s = s.extra(**extra_options)

    s = s.source(excludes=["percolator_query"])
    s = s.sort("date_created")
    s = s[: settings.ELASTICSEARCH_PAGINATION_BATCH_SIZE]
    if search_after:
        s = s.extra(search_after=search_after)
    return s.execute()
