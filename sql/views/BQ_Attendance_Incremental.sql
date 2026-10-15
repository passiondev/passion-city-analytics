CREATE OR ALTER VIEW dbo.BQ_Attendance_Incremental AS
SELECT
    Id,
    DeviceId,
    SearchTypeValueId,
    AttendanceCodeId,
    QualifierValueId,
    StartDateTime,
    EndDateTime,
    DidAttend,
    Note,
    CAST(Guid AS NVARCHAR(36))                              AS Guid,
    CreatedDateTime,
    ModifiedDateTime,
    CreatedByPersonAliasId,
    ModifiedByPersonAliasId,
    ForeignKey,
    CampusId,
    PersonAliasId,
    RSVP,
    Processed,
    CAST(ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
    ForeignId,
    SearchValue,
    SearchResultGroupId,
    OccurrenceId,
    CheckedInByPersonAliasId,
    ScheduledToAttend,
    RequestedToAttend,
    ScheduleConfirmationSent,
    ScheduleReminderSent,
    RSVPDateTime,
    DeclineReasonValueId,
    ScheduledByPersonAliasId,
    AttendanceCheckInSessionId,
    PresentDateTime,
    PresentByPersonAliasId,
    CheckedOutByPersonAliasId,
    IsFirstTime,
    CheckInStatus,
    SourceValueId,

    -- ingestion metadata for Make.com
    GETUTCDATE()                                            AS _loaded_at,
    'rock_rms'                                               AS _source_system

FROM dbo.Attendance
WHERE ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Attendance_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND ModifiedDateTime <= CURRENT_TIMESTAMP