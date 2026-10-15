CREATE OR ALTER VIEW dbo.BQ_Group_Member_Incremental AS
SELECT
    Id,
    IsSystem,
    GroupId,
    PersonId,
    GroupRoleId,
    GroupMemberStatus,
    CAST(Guid AS NVARCHAR(36))                              AS Guid,
    CreatedDateTime,
    ModifiedDateTime,
    CreatedByPersonAliasId,
    ModifiedByPersonAliasId,
    ForeignKey,
    GuestCount,
    DateTimeAdded,
    IsNotified,
    Note,
    CAST(ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
    ForeignId,
    GroupOrder,
    InactiveDateTime,
    IsArchived,
    ArchivedDateTime,
    ArchivedByPersonAliasId,
    ScheduleTemplateId,
    ScheduleStartDate,
    ScheduleReminderEmailOffsetDays,
    CommunicationPreference,
    GroupTypeId,
    IsChatMuted,
    IsChatBanned,

    -- ingestion metadata for Make.com
    GETUTCDATE()                                            AS _loaded_at,
    'rock_rms'                                               AS _source_system

FROM dbo.GroupMember
WHERE ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Group_Member_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND ModifiedDateTime <= CURRENT_TIMESTAMP