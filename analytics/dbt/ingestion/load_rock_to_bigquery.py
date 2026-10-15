"""
Load Rock RMS tables into BigQuery's `bronze` dataset.

Config-driven: add a new table by adding an entry to TABLE_CONFIGS below —
no new script, no code duplication. Each table is loaded independently via
the --table flag, so scheduling can add tables one at a time.

Bronze principle: land the data as close to raw as possible. We add a small
amount of ingestion metadata (_loaded_at, _source_system) but do NOT rename
columns, cast types, or apply business logic here — that all happens in dbt
staging models downstream.

Usage:
    python load_rock_to_bigquery.py --table person --mode full
    python load_rock_to_bigquery.py --table person --mode incremental
    python load_rock_to_bigquery.py --table person --mode incremental --reconcile-deletes
    python load_rock_to_bigquery.py --list-tables

Requires:
    pip install "cloud-sql-python-connector[pytds]" pandas google-cloud-bigquery db-dtypes

Environment variables expected (set these in your scheduler / secrets manager,
never hardcode credentials):
    ROCK_DB_SERVER      e.g. "10.1.2.3,1433"
    ROCK_DB_NAME        e.g. "Rock"
    ROCK_DB_USER
    ROCK_DB_PASSWORD
    GCP_PROJECT_ID      e.g. "bigquery-test-469018"
    BQ_BRONZE_DATASET   defaults to "bronze"
"""

import argparse
import datetime
import os

import pandas as pd
import pyodbc
from google.cloud import bigquery

CHUNK_SIZE = 50_000  # rows per fetch batch, tune to your memory/network

# ---------------------------------------------------------------------------
# TABLE CONFIGS — add a new table by adding an entry here.
#
#   source_table       fully-qualified source table, e.g. "dbo.Person"
#   columns             list of columns to pull (order preserved, de-duped)
#   bq_table            destination table name in bronze (per naming conventions:
#                       <source>_<entity>, plural — e.g. "rock_people")
#   primary_key         column used to upsert/merge and to reconcile deletes
#   modified_column     column used for incremental "what changed" filtering
# ---------------------------------------------------------------------------
TABLE_CONFIGS = {
    "person": {
        "source_table": "dbo.Person",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_people",
        "columns": [
            "Id",
            "IsSystem",
            "RecordTypeValueId",
            "RecordStatusValueId",
            "RecordStatusReasonValueId",
            "ConnectionStatusValueId",
            "IsDeceased",
            "TitleValueId",
            "FirstName",
            "NickName",
            "MiddleName",
            "LastName",
            "SuffixValueId",
            "PhotoId",
            "BirthDay",
            "BirthMonth",
            "BirthYear",
            "Gender",
            "MaritalStatusValueId",
            "AnniversaryDate",
            "GivingGroupId",
            "Email",
            "IsEmailActive",
            "EmailNote",
            "SystemNote",
            "ViewedCount",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "EmailPreference",
            "InactiveReasonNote",
            "ForeignKey",
            "ReviewReasonValueId",
            "ReviewReasonNote",
            "GraduationYear",
            "ForeignGuid",
            "ForeignId",
            "RecordStatusLastModifiedDateTime",
            "CommunicationPreference",
            "TopSignalColor",
            "TopSignalIconCssClass",
            "TopSignalId",
            "AgeClassification",
            "PrimaryFamilyId",
            "DaysUntilAnniversary",
            "IsLockedAsChild",
            "DeceasedDate",
            "GivingLeaderId",
            "BirthDate",
            "ContributionFinancialAccountId",
            "PrimaryCampusId",
            "GivingId",
            "PreferredLanguageValueId",
            "AccountProtectionProfile",
            "DaysUntilBirthday",
            "ReminderCount",
            "RaceValueId",
            "EthnicityValueId",
            "BirthDateKey",
            "AgeBracket",
            "Age",
            "FirstNamePronunciationOverride",
            "NickNamePronunciationOverride",
            "LastNamePronunciationOverride",
            "PronunciationNote",
            "PrimaryAliasId",
            "PrimaryAliasGuid",
            "IsChatProfilePublic",
            "IsChatOpenDirectMessageAllowed",
            "RecordSourceValueId",
        ],
    },

    "group": {
        "source_table": "dbo.[Group]",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_groups",
        "columns": [
            "Id",
            "IsSystem",
            "ParentGroupId",
            "GroupTypeId",
            "CampusId",
            "Name",
            "Description",
            "IsSecurityRole",
            "IsActive",
            "Order",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "AllowGuests",
            "ScheduleId",
            "IsPublic",
            "ForeignGuid",
            "ForeignId",
            "GroupCapacity",
            "RequiredSignatureDocumentTemplateId",
            "InactiveDateTime",
            "IsArchived",
            "ArchivedDateTime",
            "ArchivedByPersonAliasId",
            "StatusValueId",
            "GroupAdministratorPersonAliasId",
            "SchedulingMustMeetRequirements",
            "AttendanceRecordRequiredForCheckIn",
            "ScheduleCoordinatorPersonAliasId",
            "InactiveReasonValueId",
            "InactiveReasonNote",
            "RSVPReminderSystemCommunicationId",
            "RSVPReminderOffsetDays",
            "DisableScheduleToolboxAccess",
            "DisableScheduling",
            "GroupSalutation",
            "GroupSalutationFull",
            "ElevatedSecurityLevel",
            "ConfirmationAdditionalDetails",
            "ReminderSystemCommunicationId",
            "ReminderOffsetDays",
            "ReminderAdditionalDetails",
            "ScheduleConfirmationLogic",
            "RelationshipGrowthEnabledOverride",
            "RelationshipStrengthOverride",
            "LeaderToLeaderRelationshipMultiplierOverride",
            "LeaderToNonLeaderRelationshipMultiplierOverride",
            "NonLeaderToNonLeaderRelationshipMultiplierOverride",
            "NonLeaderToLeaderRelationshipMultiplierOverride",
            "IsSpecialNeeds",
            "ScheduleCoordinatorNotificationTypes",
            "IsChatEnabledOverride",
            "IsLeavingChatChannelAllowedOverride",
            "IsChatChannelPublicOverride",
            "IsChatChannelAlwaysShownOverride",
            "ChatChannelKey",
            "GroupMemberRecordSourceValueId",
            "ChatChannelAvatarBinaryFileId",
            "ChatPushNotificationModeOverride",
        ],
    },

    "person_historical": {
        "source_table": "dbo.AnalyticsDimPersonHistorical",
        "primary_key": "Id",
        "modified_column": "EffectiveDate",  # unused — this table is loaded via --mode full only
        "bq_table": "rock_analytics_dim_person_historical",
        "columns": [
            "Id",
            "PersonId",
            "CurrentRowIndicator",
            "EffectiveDate",
            "ExpireDate",
            "PrimaryFamilyId",
            "RecordTypeValueId",
            "RecordStatusValueId",
            "RecordStatusLastModifiedDateTime",
            "RecordStatusReasonValueId",
            "ConnectionStatusValueId",
            "ReviewReasonValueId",
            "IsDeceased",
            "TitleValueId",
            "FirstName",
            "NickName",
            "MiddleName",
            "LastName",
            "SuffixValueId",
            "PhotoId",
            "BirthDay",
            "BirthMonth",
            "BirthYear",
            "BirthDateKey",
            "Age",
            "Gender",
            "MaritalStatusValueId",
            "AnniversaryDate",
            "GraduationYear",
            "GivingGroupId",
            "GivingId",
            "GivingLeaderId",
            "Email",
            "EmailPreference",
            "ReviewReasonNote",
            "InactiveReasonNote",
            "SystemNote",
            "ViewedCount",
            "Guid",
            "ForeignId",
            "ForeignGuid",
            "ForeignKey",
            "Count",
            "core_CurrentlyAnEra",
            "core_EraStartDate",
            "core_EraFirstGave",
            "core_EraLastGave",
            "core_TimesCheckedIn16Wks",
            "core_EraTimesGiven52Wks",
            "core_EraTimesGiven6Wks",
            "CurrentJourneyGivingStage",
            "FrequencyLabel",
            "GiftAmountIQR",
            "GiftAmountMedian",
            "GiftFrequencyDaysMean",
            "GiftFrequencyDaysStandardDeviation",
            "GivingBin",
            "GivingPercentile",
            "LastClassificationRunDateTime",
            "NextExpectedGiftDate",
            "PreferredCurrency",
            "PreviousJourneyGivingStage",
            "JourneyGivingStageChangeDate",
            "DonorFundsOrganization",
            "MaritalStatus",
            "ConnectionStatus",
            "ReviewReason",
            "RecordStatus",
            "RecordStatusReason",
            "RecordType",
            "Suffix",
            "Title",
            "GenderText",
            "EmailPreferenceText",
            "CampusId",
            "CampusName",
            "CampusShortCode",
            "PrimaryFamilyKey",
            "MailingAddressStreet1",
            "MailingAddressStreet2",
            "MailingAddressCity",
            "MailingAddressCounty",
            "MailingAddressState",
            "MailingAddressCountry",
            "MailingAddressPostalCode",
            "MailingAddressLatitude",
            "MailingAddressLongitude",
            "MailingAddressFull",
            "MappedAddressStreet1",
            "MappedAddressStreet2",
            "MappedAddressCity",
            "MappedAddressCounty",
            "MappedAddressState",
            "MappedAddressCountry",
            "MappedAddressPostalCode",
            "MappedAddressLatitude",
            "MappedAddressLongitude",
            "MappedAddressFull",
        ],
    },

        "transaction": {
        "source_table": "dbo.FinancialTransaction",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_financial_transactions",
        "columns": [
            "Id",
            "BatchId",
            "TransactionDateTime",
            "TransactionCode",
            "Summary",
            "TransactionTypeValueId",
            "SourceTypeValueId",
            "CheckMicrEncrypted",
            "ScheduledTransactionId",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "ProcessedByPersonAliasId",
            "ProcessedDateTime",
            "CheckMicrHash",
            "AuthorizedPersonAliasId",
            "FinancialGatewayId",
            "FinancialPaymentDetailId",
            "MICRStatus",
            "CheckMicrParts",
            "ForeignGuid",
            "ForeignId",
            "Status",
            "StatusMessage",
            "IsSettled",
            "SettledGroupId",
            "SettledDate",
            "IsReconciled",
            "ShowAsAnonymous",
            "FutureProcessingDateTime",
            "NonCashAssetTypeValueId",
            "SundayDate",
            "TransactionDateKey",
            "SettledDateKey",
            "ForeignCurrencyCodeValueId",
        ],
    },

    "transaction_detail": {
        "source_table": "dbo.FinancialTransactionDetail",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_financial_transaction_details",
        "numeric_columns": ["Amount", "FeeAmount", "FeeCoverageAmount", "ForeignCurrencyAmount"],
        "columns": [
            "Id", "TransactionId", "AccountId", "Amount", "Summary",
            "EntityTypeId", "EntityId", "Guid", "CreatedDateTime",
            "ModifiedDateTime", "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId", "ForeignKey", "ForeignGuid",
            "ForeignId", "FeeAmount", "FeeCoverageAmount",
            "ForeignCurrencyAmount",
        ],
    },

        "group_member": {
        "source_table": "dbo.GroupMember",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_group_members",
        "columns": [
            "Id",
            "IsSystem",
            "GroupId",
            "PersonId",
            "GroupRoleId",
            "GroupMemberStatus",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "GuestCount",
            "DateTimeAdded",
            "IsNotified",
            "Note",
            "ForeignGuid",
            "ForeignId",
            "GroupOrder",
            "InactiveDateTime",
            "IsArchived",
            "ArchivedDateTime",
            "ArchivedByPersonAliasId",
            "ScheduleTemplateId",
            "ScheduleStartDate",
            "ScheduleReminderEmailOffsetDays",
            "CommunicationPreference",
            "GroupTypeId",
            "IsChatMuted",
            "IsChatBanned",
        ],
    },

        "attendance": {
        "source_table": "dbo.Attendance",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_attendance",
        "columns": [
            "Id",
            "DeviceId",
            "SearchTypeValueId",
            "AttendanceCodeId",
            "QualifierValueId",
            "StartDateTime",
            "EndDateTime",
            "DidAttend",
            "Note",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "CampusId",
            "PersonAliasId",
            "RSVP",
            "Processed",
            "ForeignGuid",
            "ForeignId",
            "SearchValue",
            "SearchResultGroupId",
            "OccurrenceId",
            "CheckedInByPersonAliasId",
            "ScheduledToAttend",
            "RequestedToAttend",
            "ScheduleConfirmationSent",
            "ScheduleReminderSent",
            "RSVPDateTime",
            "DeclineReasonValueId",
            "ScheduledByPersonAliasId",
            "AttendanceCheckInSessionId",
            "PresentDateTime",
            "PresentByPersonAliasId",
            "CheckedOutByPersonAliasId",
            "IsFirstTime",
            "CheckInStatus",
            "SourceValueId",
        ],
    },

        "attendance_occurrence": {
        "source_table": "dbo.AttendanceOccurrence",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_attendance_occurrences",
        "columns": [
            "Id",
            "GroupId",
            "LocationId",
            "ScheduleId",
            "OccurrenceDate",
            "DidNotOccur",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "Guid",
            "ForeignId",
            "ForeignGuid",
            "ForeignKey",
            "Notes",
            "AnonymousAttendanceCount",
            "StepTypeId",
            "AcceptConfirmationMessage",
            "DeclineConfirmationMessage",
            "ShowDeclineReasons",
            "DeclineReasonValueIds",
            "SundayDate",
            "Name",
            "OccurrenceDateKey",
            "AttendanceTypeValueId",
            "AttendanceReminderLastSentDateTime",
            "RootGroupTypeId",
        ],
    },

        "connection_request": {
        "source_table": "dbo.ConnectionRequest",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_connection_requests",
        "columns": [
            "Id",
            "ConnectionOpportunityId",
            "PersonAliasId",
            "Comments",
            "ConnectionStatusId",
            "ConnectionState",
            "FollowupDate",
            "CampusId",
            "AssignedGroupId",
            "ConnectorPersonAliasId",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "Guid",
            "ForeignKey",
            "ForeignGuid",
            "ForeignId",
            "AssignedGroupMemberRoleId",
            "AssignedGroupMemberStatus",
            "AssignedGroupMemberAttributeValues",
            "CreatedDateKey",
            "Order",
            "ConnectionTypeId",
            "ConnectionTypeSourceId",
            "DueDate",
            "DueSoonDate",
            "ConnectedDateTime",
            "WasCompletedOnTime",
        ],
    },

        "financial_account": {
        "source_table": "dbo.FinancialAccount",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_financial_accounts",
        "columns": [
            "Id",
            "ParentAccountId",
            "CampusId",
            "Name",
            "PublicName",
            "Description",
            "IsTaxDeductible",
            "GlCode",
            "Order",
            "IsActive",
            "StartDate",
            "EndDate",
            "AccountTypeValueId",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "ImageBinaryFileId",
            "Url",
            "PublicDescription",
            "IsPublic",
            "ForeignGuid",
            "ForeignId",
            "UsesCampusChildAccounts",
        ],
    },

    "person_alias": {
        "source_table": "dbo.PersonAlias",
        "primary_key": "Id",
        # PersonAlias has no ModifiedDateTime or CreatedDateTime, so there is
        # nothing to filter incrementally on. This table is loaded with
        # --mode full only, and modified_column is unused.
        "modified_column": "AliasedDateTime",
        "bq_table": "rock_person_aliases",
        "columns": [
            "Id",
            "Name",
            "PersonId",
            "AliasPersonId",
            "AliasPersonGuid",
            "Guid",
            "ForeignKey",
            "ForeignGuid",
            "ForeignId",
            "AliasedDateTime",
            "LastVisitDateTime",
            "InternalMessage",
        ],
    },

    "defined_value": {
        "source_table": "dbo.DefinedValue",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_defined_values",
        "columns": [
            "Id",
            "IsSystem",
            "DefinedTypeId",
            "Order",
            "Value",
            "Description",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "ForeignGuid",
            "ForeignId",
            "IsActive",
            "CategoryId",
        ],
    },

    "group_type": {
        "source_table": "dbo.GroupType",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_group_types",
        # The four relationship multipliers are decimals. Listing them here
        # makes the loader store them as exact NUMERIC instead of letting
        # BigQuery guess a type from whichever values happen to be present.
        "numeric_columns": [
            "LeaderToLeaderRelationshipMultiplier",
            "LeaderToNonLeaderRelationshipMultiplier",
            "NonLeaderToNonLeaderRelationshipMultiplier",
            "NonLeaderToLeaderRelationshipMultiplier",
        ],
        "columns": [
            "Id",
            "IsSystem",
            "Name",
            "Description",
            "GroupTerm",
            "GroupMemberTerm",
            "DefaultGroupRoleId",
            "AllowMultipleLocations",
            "ShowInGroupList",
            "ShowInNavigation",
            "IconCssClass",
            "TakesAttendance",
            "AttendanceRule",
            "AttendancePrintTo",
            "Order",
            "InheritedGroupTypeId",
            "LocationSelectionMode",
            "GroupTypePurposeValueId",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "EnableLocationSchedules",
            "AllowedScheduleTypes",
            "SendAttendanceReminder",
            "IgnorePersonInactivated",
            "ForeignGuid",
            "ForeignId",
            "ShowConnectionStatus",
            "AttendanceCountsAsWeekendService",
            "GroupCapacityRule",
            "GroupsRequireCampus",
            "GroupAttendanceRequiresLocation",
            "GroupAttendanceRequiresSchedule",
            "IsIndexEnabled",
            "ShowMaritalStatus",
            "GroupViewLavaTemplate",
            "AllowSpecificGroupMemberAttributes",
            "EnableSpecificGroupRequirements",
            "AllowGroupSync",
            "AllowSpecificGroupMemberWorkflows",
            "EnableGroupHistory",
            "GroupTypeColor",
            "GroupStatusDefinedTypeId",
            "AdministratorTerm",
            "ShowAdministrator",
            "EnableGroupTag",
            "IsSchedulingEnabled",
            "ScheduleCancellationWorkflowTypeId",
            "ScheduleConfirmationEmailOffsetDays",
            "ScheduleReminderEmailOffsetDays",
            "RequiresReasonIfDeclineSchedule",
            "EnableRSVP",
            "EnableInactiveReason",
            "RequiresInactiveReason",
            "AllowAnyChildGroupType",
            "ScheduleConfirmationSystemCommunicationId",
            "ScheduleReminderSystemCommunicationId",
            "RSVPReminderSystemCommunicationId",
            "RSVPReminderOffsetDays",
            "IsCapacityRequired",
            "ScheduleConfirmationLogic",
            "AttendanceReminderSystemCommunicationId",
            "AttendanceReminderSendStartOffsetMinutes",
            "AttendanceReminderFollowupDays",
            "IsPeerNetworkEnabled",
            "RelationshipGrowthEnabled",
            "RelationshipStrength",
            "LeaderToLeaderRelationshipMultiplier",
            "LeaderToNonLeaderRelationshipMultiplier",
            "NonLeaderToNonLeaderRelationshipMultiplier",
            "NonLeaderToLeaderRelationshipMultiplier",
            "AlreadyEnrolledMatchingLogic",
            "ScheduleCoordinatorNotificationTypes",
            "IsConcurrentCheckInPrevented",
            "IsChatAllowed",
            "IsChatEnabledForAllGroups",
            "IsLeavingChatChannelAllowed",
            "IsChatChannelPublic",
            "IsChatChannelAlwaysShown",
            "GroupMemberRecordSourceValueId",
            "AllowGroupSpecificRecordSource",
            "ChatPushNotificationMode",
            "AdditionalSettingsJson",
        ],
    },

    "campus": {
        "source_table": "dbo.Campus",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_campuses",
        # TitheMetric is a decimal. Listing it here stores it as exact
        # NUMERIC instead of letting BigQuery guess from the values present.
        "numeric_columns": ["TitheMetric"],
        "columns": [
            "Id",
            "IsSystem",
            "Name",
            "ShortCode",
            "LocationId",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "ForeignKey",
            "PhoneNumber",
            "LeaderPersonAliasId",
            "ServiceTimes",
            "Description",
            "IsActive",
            "Url",
            "ForeignGuid",
            "ForeignId",
            "Order",
            "TimeZoneId",
            "CampusStatusValueId",
            "CampusTypeValueId",
            "TeamGroupId",
            "OpenedDate",
            "ClosedDate",
            "TitheMetric",
            "BeaconId",
            "AverageWeekendAttendance",
        ],
    },

    "connection_opportunity": {
        "source_table": "dbo.ConnectionOpportunity",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_connection_opportunities",
        "columns": [
            "Id",
            "Name",
            "PublicName",
            "Description",
            "PhotoId",
            "ConnectionTypeId",
            "IconCssClass",
            "IsActive",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "Guid",
            "ForeignKey",
            "Summary",
            "ForeignGuid",
            "ForeignId",
            "Order",
            "ShowStatusOnTransfer",
            "ShowConnectButton",
            "ShowCampusOnTransfer",
            "AdditionalSettingsJson",
            "RequestDueSoonOffsetInDays",
            "RequestDueDateOffsetInDays",
        ],
    },

    # Example of what adding a second table looks like — fill in real columns
    # before using. Rock's Group table is a common next candidate (families,
    # small groups, serving teams all live here).
    #
    # "group": {
    #     "source_table": "dbo.Group",
    #     "primary_key": "Id",
    #     "modified_column": "ModifiedDateTime",
    #     "bq_table": "rock_groups",
    #     "columns": [
    #         "Id",
    #         "Guid",
    #         "GroupTypeId",
    #         "Name",
    #         "IsActive",
    #         "ParentGroupId",
    #         "CampusId",
    #         "CreatedDateTime",
    #         "ModifiedDateTime",
    #     ],
    # },
}


def get_sql_server_connection() -> pyodbc.Connection:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['ROCK_DB_SERVER']};"
        f"DATABASE={os.environ['ROCK_DB_NAME']};"
        f"UID={os.environ['ROCK_DB_USER']};"
        f"PWD={os.environ['ROCK_DB_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def build_query(config: dict, mode: str) -> str:
    cols = ", ".join(f"[{c}]" for c in dict.fromkeys(config["columns"]))  # de-dupe, preserve order
    base = f"SELECT {cols} FROM {config['source_table']}"
    if mode == "incremental":
        # Adjust the lookback window to match your load schedule + tolerance
        # for late-arriving edits. 26 hours covers a daily job with slack.
        base += f" WHERE [{config['modified_column']}] >= DATEADD(HOUR, -26, GETUTCDATE())"
    return base


def extract(config: dict, mode: str) -> pd.DataFrame:
    query = build_query(config, mode)
    with get_sql_server_connection() as conn:
        chunks = pd.read_sql(query, conn, chunksize=CHUNK_SIZE)
        df = pd.concat(chunks, ignore_index=True)

    from decimal import Decimal
    for col in config.get("numeric_columns", []):
        if col in df.columns:
            df[col] = df[col].apply(lambda x: Decimal(str(x)) if pd.notnull(x) else None)

    # Some columns come back from pyodbc/pandas as ambiguous "object" dtype
    # rather than a clean numeric type -- often when a batch happens to mix
    # nulls with numeric values in a way pandas can't unify on its own.
    # build_explicit_schema() would otherwise default these to STRING, which
    # then fails outright once BigQuery's writer hits an actual numeric
    # value inside a column declared as STRING. Coerce any object column
    # that is really numeric underneath before schema-building ever sees it.
    numeric_cols = set(config.get("numeric_columns", []))
    for col in df.columns:
        if col in numeric_cols:
            continue  # already handled above as Decimal
        if df[col].dtype == object:
            if df[col].notna().sum() == 0:
                continue  # all-null column: leave as object so it lands as STRING
            # nullable bit columns come back as object dtype holding
            # True/False/None. Keep them as real booleans -- pd.to_numeric
            # would turn them into 1.0/0.0 floats and BigQuery would land
            # them as FLOAT64.
            non_null = df[col].dropna()
            if len(non_null) > 0 and all(isinstance(v, bool) for v in non_null):
                df[col] = df[col].astype("boolean")
                continue
            # try numeric first
            coerced_numeric = pd.to_numeric(df[col], errors="coerce")
            if coerced_numeric.notna().sum() == df[col].notna().sum():
                df[col] = coerced_numeric
                continue
            # not numeric -- try datetime (covers columns like
            # ProcessedDateTime that pandas/pyodbc left as ambiguous
            # "object" dtype instead of a clean datetime64 column, usually
            # because of a mix of real timestamps and nulls)
            coerced_datetime = pd.to_datetime(df[col], errors="coerce")
            if coerced_datetime.notna().sum() == df[col].notna().sum():
                df[col] = coerced_datetime

    df["_loaded_at"] = datetime.datetime.utcnow()
    df["_source_system"] = "rock_rms"
    return df

def build_explicit_schema(df: pd.DataFrame, config: dict) -> list:
    """
    Build a BigQuery schema explicitly rather than relying on autodetect.
    Columns listed in config["numeric_columns"] are forced to NUMERIC
    (exact decimal — correct for money, unlike FLOAT64) regardless of
    whether this particular batch happens to have nulls or values in them.
    Locking this in at load time also prevents future incremental loads
    from drifting to a different inferred type, the same class of bug that
    broke the person table's merge earlier.
    """
    numeric_columns = set(config.get("numeric_columns", []))
    schema = []
    for col in df.columns:
        if col in numeric_columns:
            schema.append(bigquery.SchemaField(col, "NUMERIC"))
        elif pd.api.types.is_bool_dtype(df[col]):
            schema.append(bigquery.SchemaField(col, "BOOLEAN"))
        elif pd.api.types.is_integer_dtype(df[col]):
            schema.append(bigquery.SchemaField(col, "INTEGER"))
        elif pd.api.types.is_float_dtype(df[col]):
            schema.append(bigquery.SchemaField(col, "FLOAT"))
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            schema.append(bigquery.SchemaField(col, "TIMESTAMP"))
        else:
            schema.append(bigquery.SchemaField(col, "STRING"))
    return schema


def load_to_bigquery(df: pd.DataFrame, config: dict, mode: str) -> None:
    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_BRONZE_DATASET", "bronze")
    bq_table = config["bq_table"]
    pk = config["primary_key"]
    table_ref = f"{project_id}.{dataset}.{bq_table}"

    client = bigquery.Client(project=project_id)

    if mode == "full":
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        job_config = bigquery.LoadJobConfig(
            write_disposition=write_disposition,
            schema=build_explicit_schema(df, config),
        )
    else:
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        table_ref = f"{project_id}.{dataset}._stg_{bq_table}"

        # Reuse the target table's existing schema rather than autodetect.
        # autodetect infers types independently per load based on whatever
        # sample of rows is present — a batch where a column happens to be
        # all-null can get inferred as a different type (e.g. STRING
        # instead of FLOAT64) than the original full load saw, causing the
        # MERGE below to fail on a type mismatch. Locking to the target's
        # committed schema keeps every incremental load type-consistent.
        target_table = client.get_table(f"{project_id}.{dataset}.{bq_table}")
        staging_schema = [field for field in target_table.schema]
        job_config = bigquery.LoadJobConfig(
            write_disposition=write_disposition,
            schema=staging_schema,
        )
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()
    print(f"Loaded {len(df):,} rows into {table_ref}")

    if mode == "incremental":
        update_cols = [c for c in dict.fromkeys(config["columns"]) if c != pk]
        merge_sql = f"""
        MERGE `{project_id}.{dataset}.{bq_table}` T
        USING `{table_ref}` S
        ON T.{pk} = S.{pk}
        WHEN MATCHED THEN UPDATE SET
          {", ".join(f"T.{c} = S.{c}" for c in update_cols)},
          T._loaded_at = S._loaded_at
        WHEN NOT MATCHED THEN INSERT ROW
        """
        client.query(merge_sql).result()
        client.query(f"DROP TABLE `{table_ref}`").result()
        print(f"Merged incremental batch into {dataset}.{bq_table}")


def reconcile_deletes(config: dict, project_id: str, dataset: str) -> None:
    """
    Polling by modified_column never sees hard deletes on the Rock side (a
    row that's gone doesn't show up as a "changed" row to poll for). This
    pulls the full current set of primary keys from Rock and removes any
    bronze row no longer present. Run this less frequently than the main
    incremental job (e.g. nightly) since it requires a full scan of the
    source table's primary key column.
    """
    pk = config["primary_key"]
    bq_table = config["bq_table"]

    with get_sql_server_connection() as conn:
        current_ids = pd.read_sql(f"SELECT {pk} FROM {config['source_table']}", conn)

    client = bigquery.Client(project=project_id)
    ids_table = f"{project_id}.{dataset}._current_{bq_table}_ids"
    job = client.load_table_from_dataframe(
        current_ids,
        ids_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    )
    job.result()

    delete_sql = f"""
    DELETE FROM `{project_id}.{dataset}.{bq_table}` T
    WHERE T.{pk} NOT IN (SELECT {pk} FROM `{ids_table}`)
    """
    result = client.query(delete_sql).result()
    print(f"Reconciled deletes against {ids_table}; removed {result.num_dml_affected_rows or 0} rows")
    client.query(f"DROP TABLE `{ids_table}`").result()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
    "--table",
    choices=sorted(TABLE_CONFIGS.keys()) + ["all"],
    help="Which configured table to load, or 'all' to load every configured table",
)
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument(
        "--reconcile-deletes",
        action="store_true",
        help="After loading, remove bronze rows whose primary key no longer exists in Rock. "
             "Run this on a slower cadence (e.g. nightly) than the main incremental job.",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="Print configured table keys and exit.",
    )
    args = parser.parse_args()

    if args.list_tables:
        for key, cfg in TABLE_CONFIGS.items():
            print(f"{key:12s} -> {cfg['source_table']:20s} -> bronze.{cfg['bq_table']}")
        return

    if not args.table:
        parser.error("--table is required (use 'all' for every configured table, or --list-tables to see options)")

    tables_to_run = list(TABLE_CONFIGS.keys()) if args.table == "all" else [args.table]

    for table_key in tables_to_run:
        print(f"--- {table_key} ---")
        config = TABLE_CONFIGS[table_key]

        df = extract(config, args.mode)
        if df.empty:
            print("No rows extracted; skipping.")
        else:
            load_to_bigquery(df, config, args.mode)

        if args.reconcile_deletes:
            project_id = os.environ["GCP_PROJECT_ID"]
            dataset = os.environ.get("BQ_BRONZE_DATASET", "bronze")
            reconcile_deletes(config, project_id, dataset)


if __name__ == "__main__":
    main()
